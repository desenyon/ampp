use ampp_core::verification::cascade::{PythonVerifyRequest, PythonVerifyResponse};
use anyhow::{Context, Result};
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::{Arc, Mutex};
use tracing::{debug, info};

/// Manages a long-lived Python worker subprocess.
/// Communication is newline-delimited JSON over stdin/stdout.
pub struct PythonWorker {
    child: Arc<Mutex<Child>>,
    stdin: Arc<Mutex<ChildStdin>>,
    reader: Arc<Mutex<BufReader<ChildStdout>>>,
}

impl PythonWorker {
    /// Spawn the Python worker process.
    ///
    /// `python_path`  – path to the Python interpreter (e.g. `venv/bin/python`)  
    /// `worker_script` – path to `ampp/worker.py`
    pub fn spawn(python_path: &str, worker_script: &str) -> Result<Self> {
        info!("Spawning Python worker: {} {}", python_path, worker_script);
        let mut child = Command::new(python_path)
            .arg("-u") // unbuffered
            .arg(worker_script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .context("Failed to spawn Python worker")?;

        let stdin = child.stdin.take().context("No stdin on Python worker")?;
        let stdout = child.stdout.take().context("No stdout on Python worker")?;

        Ok(Self {
            child: Arc::new(Mutex::new(child)),
            stdin: Arc::new(Mutex::new(stdin)),
            reader: Arc::new(Mutex::new(BufReader::new(stdout))),
        })
    }

    /// Send a verify request and block until a response arrives.
    pub fn call(&self, request: PythonVerifyRequest) -> Result<PythonVerifyResponse> {
        let payload = serde_json::to_string(&request)? + "\n";
        debug!(request_id = %request.request_id, stage = %request.stage, "→ Python");

        {
            let mut stdin = self.stdin.lock().unwrap();
            stdin
                .write_all(payload.as_bytes())
                .context("Write to Python worker failed")?;
            stdin.flush()?;
        }

        let mut line = String::new();
        {
            let mut reader = self.reader.lock().unwrap();
            reader
                .read_line(&mut line)
                .context("Read from Python worker failed")?;
        }

        if line.is_empty() {
            anyhow::bail!("Python worker closed its stdout unexpectedly");
        }

        let response: PythonVerifyResponse =
            serde_json::from_str(line.trim()).context("Deserialising Python response")?;
        debug!(request_id = %response.request_id, passed = %response.passed, "← Python");

        Ok(response)
    }

    /// Gracefully shut down the worker.
    pub fn shutdown(&self) -> Result<()> {
        let shutdown = serde_json::json!({ "type": "shutdown" });
        let payload = serde_json::to_string(&shutdown)? + "\n";
        if let Ok(mut stdin) = self.stdin.lock() {
            let _ = stdin.write_all(payload.as_bytes());
            let _ = stdin.flush();
        }
        if let Ok(mut child) = self.child.lock() {
            let _ = child.wait();
        }
        Ok(())
    }
}

impl Drop for PythonWorker {
    fn drop(&mut self) {
        let _ = self.shutdown();
    }
}
