"""Integration tests for the Python worker JSON-RPC protocol.

These tests exercise the ``handle()`` function directly without spawning
a subprocess, which keeps them fast and CI-friendly.
"""
from __future__ import annotations

import uuid

import pytest

# Import handle directly to avoid subprocess overhead in unit tests
from ampp.worker import handle


def _req(stage: str, context: dict | None = None, candidate: dict | None = None) -> dict:
    return {
        "request_id": str(uuid.uuid4()),
        "stage": stage,
        "candidate_json": candidate or {},
        "context": context or {},
    }


class TestWorkerHandle:
    def test_normalise_returns_formal_spec(self):
        resp = handle(_req("NORMALISE", context={"problem": "For all n in N, n >= 0"}))
        assert resp["passed"] is True
        details = resp["details"]
        assert "canonical_statement" in details
        assert "target" in details

    def test_normalise_empty_problem(self):
        resp = handle(_req("NORMALISE", context={"problem": ""}))
        assert resp["passed"] is True

    def test_propose_returns_candidates_list(self):
        resp = handle(
            _req(
                "PROPOSE",
                context={
                    "subgoal_id": "sg-1",
                    "branch_id": "b-1",
                    "spec": {
                        "raw_statement": "For all n, n*(n+1) is even",
                        "canonical_statement": "for all n, n*(n+1) is even",
                        "target": "for all n, n*(n+1) is even",
                        "variables": {"n": "N"},
                        "edge_cases": [],
                    },
                    "verified_claims": [],
                    "attempts": [],
                    "rejected_hashes": [],
                },
            )
        )
        assert resp["passed"] is True
        assert "candidates" in resp["details"]
        assert isinstance(resp["details"]["candidates"], list)

    def test_unknown_stage_passes_conservatively(self):
        resp = handle(_req("UNKNOWN_STAGE"))
        assert resp["passed"] is True
        assert "unknown stage" in resp["details"].get("note", "")

    def test_v1_with_valid_candidate(self):
        import hashlib
        cand = {
            "id": str(uuid.uuid4()),
            "subgoal_id": "sg-1",
            "action_type": "introduce_lemma",
            "new_claims": [{"statement": "n >= 0", "claim_type": "lemma"}],
            "dependencies": [],
            "verification_plan": {"stages": ["V0", "V1"], "success_criteria": {}},
            "small_case_tests": [],
            "lean_stub": "-- stub",
            "strategy_family": "induction",
            "candidate_hash": hashlib.sha256(b"v1-test").hexdigest(),
            "branch_id": "b-1",
        }
        resp = handle(_req("V1", candidate=cand))
        assert "passed" in resp
        assert isinstance(resp["passed"], bool)

    def test_v2_trivial_identity(self):
        import hashlib
        cand = {
            "id": str(uuid.uuid4()),
            "subgoal_id": "sg-2",
            "action_type": "apply_transform",
            "new_claims": [{"statement": "2 + 2 = 4", "claim_type": "lemma"}],
            "dependencies": [],
            "verification_plan": {"stages": ["V2"]},
            "small_case_tests": [],
            "lean_stub": "theorem t : 2 + 2 = 4 := by norm_num",
            "strategy_family": "algebraic_normalization",
            "candidate_hash": hashlib.sha256(b"v2-test").hexdigest(),
            "branch_id": "b-1",
        }
        resp = handle(_req("V2", candidate=cand))
        assert resp["passed"] is True

    def test_request_id_echoed(self):
        rid = "my-special-request-id"
        req = _req("NORMALISE", context={"problem": "test"})
        req["request_id"] = rid
        resp = handle(req)
        assert resp["request_id"] == rid

    def test_worker_exception_returns_failed(self):
        """Malformed candidate_json should produce a graceful error response."""
        req = _req("V1", candidate={"invalid": "schema"})
        resp = handle(req)
        assert resp["passed"] is False
        assert "worker exception" in resp["details"].get("reason", "")
