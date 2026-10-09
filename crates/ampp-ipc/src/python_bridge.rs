use ampp_core::verification::cascade::{PythonVerifyRequest, PythonVerifyResponse};
use anyhow::{Context, Result};
use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;

struct WorkerState {
    child: Child,
    stdin: Arc<Mutex<ChildStdin>>,
    responses: mpsc::Receiver<std::io::Result<String>>,
    stopped: bool,
}

/// A serialized, deadline-bounded JSON line channel to a Python worker.
/// A transport error poisons the worker so late responses cannot be reused.
pub struct PythonWorker {
    state: Mutex<WorkerState>,
    timeout: Duration,
}

impl PythonWorker {
    /// Spawn a script, or use `ampp.worker` to run the installed module.
    pub fn spawn(python_path: &str, worker_script: &str) -> Result<Self> {
        Self::spawn_with_timeout(python_path, worker_script, Duration::from_secs(300))
    }

    /// Spawn a worker with a deadline for each complete request/response exchange.
    pub fn spawn_with_timeout(
        python_path: &str,
        worker_script: &str,
        timeout: Duration,
    ) -> Result<Self> {
        anyhow::ensure!(!timeout.is_zero(), "Worker timeout must be positive");
        let mut command = Command::new(python_path);
        command.arg("-u");
        if worker_script == "ampp.worker" {
            command.args(["-m", "ampp.worker"]);
        } else {
            command.arg(worker_script);
        }
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .context("Failed to spawn Python worker")?;
        let stdin = child.stdin.take().context("No worker stdin")?;
        let stdout = child.stdout.take().context("No worker stdout")?;
        let (sender, responses) = mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                let read = reader
                    .by_ref()
                    .take((MAX_RESPONSE_BYTES + 1) as u64)
                    .read_line(&mut line);
                let value = match read {
                    Ok(0) => Err(std::io::Error::new(
                        std::io::ErrorKind::UnexpectedEof,
                        "Python worker closed stdout",
                    )),
                    Ok(_) if line.len() > MAX_RESPONSE_BYTES => Err(std::io::Error::new(
                        std::io::ErrorKind::InvalidData,
                        "Python response exceeded 8 MiB",
                    )),
                    Ok(_) => Ok(line),
                    Err(error) => Err(error),
                };
                let failed = value.is_err();
                if sender.send(value).is_err() || failed {
                    break;
                }
            }
        });
        Ok(Self {
            state: Mutex::new(WorkerState {
                child,
                stdin: Arc::new(Mutex::new(stdin)),
                responses,
                stopped: false,
            }),
            timeout,
        })
    }

    /// Serialize callers and validate correlation IDs as part of the transport.
    pub fn call(&self, request: PythonVerifyRequest) -> Result<PythonVerifyResponse> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| anyhow::anyhow!("Worker lock poisoned"))?;
        anyhow::ensure!(
            !state.stopped,
            "Python worker is stopped; start a new worker"
        );
        let exchange = (|| -> Result<PythonVerifyResponse> {
            let payload = serde_json::to_string(&request)? + "\n";
            anyhow::ensure!(
                payload.len() <= MAX_RESPONSE_BYTES,
                "Python request exceeded 8 MiB"
            );
            let deadline = Instant::now() + self.timeout;
            let stdin = Arc::clone(&state.stdin);
            let (sent, written) = mpsc::sync_channel(1);
            std::thread::spawn(move || {
                let result = (|| -> Result<()> {
                    let mut writer = stdin
                        .lock()
                        .map_err(|_| anyhow::anyhow!("Worker stdin lock poisoned"))?;
                    writer.write_all(payload.as_bytes())?;
                    writer.flush()?;
                    Ok(())
                })();
                let _ = sent.send(result);
            });
            written
                .recv_timeout(self.timeout)
                .context("Python worker write deadline")??;
            let remaining = deadline.saturating_duration_since(Instant::now());
            let line = state
                .responses
                .recv_timeout(remaining)
                .context("Python worker response deadline or channel closed")??;
            let response: PythonVerifyResponse =
                serde_json::from_str(&line).context("Invalid Python response JSON")?;
            anyhow::ensure!(
                response.request_id == request.request_id && response.stage == request.stage,
                "Mismatched Python response request_id or stage"
            );
            Ok(response)
        })();
        if exchange.is_err() {
            stop(&mut state);
        }
        exchange
    }

    /// Give the worker a short grace period, then kill and reap it and its group.
    pub fn shutdown(&self) -> Result<()> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| anyhow::anyhow!("Worker lock poisoned"))?;
        if state.stopped {
            return Ok(());
        }
        if let Ok(mut stdin) = state.stdin.lock() {
            let _ = stdin.write_all(b"{\"type\":\"shutdown\"}\n");
            let _ = stdin.flush();
        }
        let deadline = Instant::now() + Duration::from_millis(100);
        while Instant::now() < deadline {
            if matches!(state.child.try_wait(), Ok(Some(_))) {
                state.stopped = true;
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        stop(&mut state);
        Ok(())
    }
}

fn stop(state: &mut WorkerState) {
    if state.stopped {
        return;
    }
    #[cfg(unix)]
    {
        // The child was spawned as its own process-group leader. Killing the
        // group also stops solver processes when the worker exceeds its deadline.
        unsafe {
            libc::kill(-(state.child.id() as i32), libc::SIGKILL);
        }
    }
    let _ = state.child.kill();
    let _ = state.child.wait();
    state.stopped = true;
}

impl Drop for PythonWorker {
    fn drop(&mut self) {
        let _ = self.shutdown();
    }
}
