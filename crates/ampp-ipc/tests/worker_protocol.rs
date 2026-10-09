use ampp_core::verification::cascade::PythonVerifyRequest;
use ampp_ipc::PythonWorker;
use std::{
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};

struct Script(PathBuf);
impl Script {
    fn new(source: &str) -> Self {
        let path = std::env::temp_dir().join(format!("ampp-ipc-{}.py", uuid::Uuid::new_v4()));
        std::fs::write(&path, source).unwrap();
        Self(path)
    }
    fn spawn(&self, millis: u64) -> PythonWorker {
        PythonWorker::spawn_with_timeout(
            "python3",
            self.0.to_str().unwrap(),
            Duration::from_millis(millis),
        )
        .unwrap()
    }
}
impl Drop for Script {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn request(id: &str) -> PythonVerifyRequest {
    PythonVerifyRequest {
        request_id: id.into(),
        stage: "PING".into(),
        candidate_json: serde_json::json!({}),
        context: serde_json::json!({}),
    }
}
const ECHO: &str = "import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if r.get('type')=='shutdown': break\n print(json.dumps(dict(request_id=r['request_id'],stage=r['stage'],passed=True,details={},counterexample=None)),flush=True)\n";

#[test]
fn concurrent_calls_are_serialized_and_correlated() {
    let script = Script::new(ECHO);
    let worker = Arc::new(script.spawn(3000));
    let calls: Vec<_> = (0..8)
        .map(|i| {
            let worker = Arc::clone(&worker);
            std::thread::spawn(move || {
                let id = i.to_string();
                assert_eq!(worker.call(request(&id)).unwrap().request_id, id);
            })
        })
        .collect();
    for call in calls {
        call.join().unwrap();
    }
    worker.shutdown().unwrap();
    assert!(worker.call(request("after-shutdown")).is_err());
}

#[test]
fn malformed_mismatched_and_eof_responses_poison_worker() {
    for source in [
        "print('not-json',flush=True)",
        "import json; print(json.dumps(dict(request_id='wrong',stage='PING',passed=True,details={})),flush=True)",
        "pass",
        "print('x' * (8*1024*1024+1),flush=True)",
    ] {
        let script = Script::new(source); let worker = script.spawn(3000);
        assert!(worker.call(request("expected")).is_err());
        assert!(worker.call(request("next")).unwrap_err().to_string().contains("stopped"));
    }
}

#[test]
fn stalled_read_and_write_have_deadlines_and_shutdown_does_not_hang() {
    let script = Script::new("import time; time.sleep(30)");
    for big_request in [false, true] {
        let worker = script.spawn(200);
        let start = Instant::now();
        let mut req = request("timeout");
        if big_request {
            req.candidate_json = serde_json::json!({"large": "x".repeat(1024*1024)});
        }
        let error = worker.call(req).unwrap_err().to_string();
        assert!(error.contains("deadline"), "{error}");
        worker.shutdown().unwrap();
        assert!(start.elapsed() < Duration::from_secs(5));
    }
}

#[test]
fn drop_stops_worker_even_without_cooperative_shutdown() {
    let script = Script::new("import time; time.sleep(30)");
    let worker = script.spawn(1000);
    let start = Instant::now();
    drop(worker);
    assert!(start.elapsed() < Duration::from_secs(5));
}
