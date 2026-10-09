"""End-to-end tests using the real Rust binary, worker, SQLite, and Lean.

Run after cargo build: AMPP_BIN=target/debug/ampp python -m pytest tests/integration.
Lean-dependent cases skip locally if absent; CI installs the pinned toolchain.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get("AMPP_BIN", ROOT / "target/debug/ampp")).resolve()
LEAN = os.environ.get("AMPP_LEAN_BINARY", "lean")
pytestmark = pytest.mark.skipif(not BINARY.is_file(), reason="Build the Rust binary first")


def run(
    tmp_path,
    *args,
    proofs=None,
    lean=LEAN,
    output="output",
    problem="Arithmetic check",
    formal="2 + 2 = 4",
    max_iter=1,
):
    command = [
        str(BINARY),
        "--offline",
        "--python",
        sys.executable,
        "--problem",
        problem,
        "--db",
        str(tmp_path / "state.db"),
        "--output",
        str(tmp_path / output),
        "--max-iter",
        str(max_iter),
    ]
    if formal is not None:
        command += ["--formal-target", formal]
    if proofs is not None:
        file = tmp_path / "candidates.json"
        file.write_text(json.dumps(proofs))
        command += ["--candidate-file", str(file)]
    command += args
    env = {
        **os.environ,
        "AMPP_LEAN_BINARY": lean,
        "AMPP_LEAN_IMPORTS": "",
        "OPENAI_API_KEY": "fixture-key-not-real",
        "ANTHROPIC_API_KEY": "fixture-key-not-real",
    }
    env.pop("AMPP_LEAN_PROJECT", None)
    proc = subprocess.run(
        command, cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30
    )
    return proc, tmp_path / output


def manifest(output):
    data = json.loads((output / "run_manifest.json").read_text())
    for name, digest in data["artifact_hashes"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert data["schema_version"] == 2
    assert data["verification_policy"] == "lean-kernel-v1"
    return data


def test_missing_lean_v0_only_never_proves_and_logs_all_branches(tmp_path):
    proc, output = run(
        tmp_path,
        proofs=[{"statement": "2 + 2 = 4", "proof": "by decide", "stages": ["V0"]}],
        lean="/no-such-ampp-lean",
    )
    assert proc.returncode == 0, proc.stderr
    data = manifest(output)
    assert "incomplete" in data["termination_condition"]
    assert data["total_verified_claims"] == data["total_rejected_claims"] == 0
    assert data["total_unverified_attempts"] == data["total_attempts"] == 4
    assert data["lean_version"] == "unavailable"
    assert not (output / "solution.lean").exists()
    log = json.loads((output / "verification_log.json").read_text())
    assert len({a["branch_id"] for a in log["attempts"]}) == 4
    assert all(a["raw_output"]["artifacts"][-1]["result"] == "unavailable" for a in log["attempts"])


def test_output_reuse_is_refused_and_existing_file_preserved(tmp_path):
    proc, output = run(tmp_path, proofs=[], lean="/no-such-ampp-lean")
    assert proc.returncode == 0
    before = (output / "run_manifest.json").read_bytes()
    proc, _ = run(tmp_path, proofs=[])
    assert proc.returncode != 0 and "fresh --output" in proc.stderr
    assert (output / "run_manifest.json").read_bytes() == before


def test_runs_sharing_database_export_only_their_own_claims(tmp_path):
    first, first_output = run(tmp_path, proofs=[], output="first")
    second, second_output = run(tmp_path, proofs=[], output="second")
    assert first.returncode == second.returncode == 0
    assert manifest(first_output)["run_id"] != manifest(second_output)["run_id"]
    for output in [first_output, second_output]:
        graph = json.loads((output / "proof_graph.json").read_text())
        assert len(graph["claims"]) == 1  # only this run's proposed root


def test_actual_max_iterations_reported_and_no_fake_solution(tmp_path):
    proc, output = run(tmp_path, formal=None, max_iter=0)
    assert proc.returncode == 0, proc.stderr
    data = manifest(output)
    assert data["termination_condition"]["incomplete"]["reason"] == "Reached max iterations (0)"
    assert data["iterations"] == 0
    assert not (output / "solution.lean").exists()


def test_offline_research_is_incomplete_even_with_credentials(tmp_path):
    proc, output = run(
        tmp_path, formal=None, problem="For all n in N, n*(n+1) is even", lean="/no-such-ampp-lean"
    )
    assert proc.returncode == 0, proc.stderr
    data = manifest(output)
    assert "incomplete" in data["termination_condition"]
    assert data["total_verified_claims"] == 0
    assert data["total_attempts"] > 0
    assert not (output / "solution.lean").exists()


def test_doctor_observes_python_version(tmp_path):
    proc = subprocess.run(
        [str(BINARY), "--doctor", "--offline", "--python", sys.executable],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["versions"]["python"] == sys.version.split()[0]


def test_invalid_candidate_file_is_an_error(tmp_path):
    proc, _ = run(tmp_path, proofs=[{"statement": "2+2=4", "unexpected": "field"}])
    assert proc.returncode != 0 and "Invalid candidate file" in proc.stderr


requires_lean = pytest.mark.skipif(
    shutil.which(LEAN) is None, reason="Pinned Lean toolchain is required"
)


@requires_lean
def test_real_proof_export_recompiles_and_has_accurate_manifest(tmp_path):
    proofs = json.loads((ROOT / "examples/two_plus_two.json").read_text())
    proc, output = run(tmp_path, proofs=proofs)
    assert proc.returncode == 0, proc.stderr
    data = manifest(output)
    assert data["termination_condition"] == "theorem_verified"
    assert data["total_verified_claims"] == 1
    assert sum(b["verified_claims"] for b in data["beam_summary"]) == 1
    source = output / "solution.lean"
    checked = subprocess.run([LEAN, str(source)], capture_output=True, text=True, timeout=15)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "does not depend on any axioms" in checked.stdout
    log = json.loads((output / "verification_log.json").read_text())
    assert (
        log["verified_claims"][0]["verification_artifacts"][-1]["details"]["lean_source"]
        == source.read_text()
    )
    assert data["python_version"] == sys.version.split()[0]
    assert "4.19.0" in data["lean_version"]


@requires_lean
def test_false_proof_is_rejected_with_diagnostics(tmp_path):
    proc, output = run(
        tmp_path, formal="2 + 2 = 5", proofs=[{"statement": "2 + 2 = 5", "proof": "by decide"}]
    )
    assert proc.returncode == 0, proc.stderr
    data = manifest(output)
    assert data["total_verified_claims"] == 0 and data["total_rejected_claims"] == 4
    assert data["total_attempts"] == 4
    assert not (output / "solution.lean").exists()
    rejected = json.loads((output / "rejected_claims.json").read_text())
    assert rejected[0]["raw_output"]["artifacts"][-1]["details"]["stdout"]


@requires_lean
def test_unrelated_true_lemma_does_not_complete_target(tmp_path):
    proc, output = run(
        tmp_path, formal="False", proofs=[{"statement": "True", "proof": "by trivial"}]
    )
    assert proc.returncode == 0, proc.stderr
    data = manifest(output)
    assert "incomplete" in data["termination_condition"]
    assert data["total_verified_claims"] == 4  # valid lemma on each branch
    assert not (output / "solution.lean").exists()


@requires_lean
def test_useful_lemma_does_not_consume_target_subgoal(tmp_path):
    proc, output = run(
        tmp_path,
        proofs=[
            {"statement": "True", "proof": "by trivial"},
            {"statement": "2 + 2 = 4", "proof": "by decide"},
        ],
    )
    assert proc.returncode == 0, proc.stderr
    data = manifest(output)
    assert data["termination_condition"] == "theorem_verified"
    assert data["total_verified_claims"] == 2


@requires_lean
def test_natural_language_run_never_claims_formal_target_completion(tmp_path):
    proc, output = run(
        tmp_path, formal=None, problem="True", proofs=[{"statement": "True", "proof": "by trivial"}]
    )
    assert proc.returncode == 0, proc.stderr
    assert "incomplete" in manifest(output)["termination_condition"]
    assert not (output / "solution.lean").exists()
