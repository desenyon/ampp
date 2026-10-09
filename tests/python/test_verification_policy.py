"""Regression tests for the trust boundary; no LLM/network access."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ampp.config import AMPPConfig, cfg
from ampp.llm import LLMProvider, NullProvider, get_provider, set_provider
from ampp.proposers.formal import FormalProofProposer
from ampp.schemas import NewClaimSpec, SmallCaseTest
from ampp.verifiers.v1_counterexample import CounterexampleVerifier
from ampp.verifiers.v2_sympy import SymPyVerifier
from ampp.verifiers.v3_z3 import Z3Verifier
from ampp.verifiers.v4_atp import ATPVerifier
from ampp.verifiers.v5_lean import LeanVerifier
from ampp.worker import handle


def proof_candidate(candidate, statement="2 + 2 = 4", proof="by decide"):
    return candidate.model_copy(
        update={
            "new_claims": [NewClaimSpec(statement=statement)],
            "lean_stub": proof,
            "small_case_tests": [],
        }
    )


def checker(monkeypatch, stdout="'ampp_claim' does not depend on any axioms\n", returncode=0):
    monkeypatch.setattr(shutil, "which", lambda _: "/fake/lean")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=""),
    )
    return LeanVerifier()


def test_null_provider_overrides_present_credentials(monkeypatch):
    set_provider(None)
    monkeypatch.setenv("AMPP_LLM_PROVIDER", "null")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-not-a-real-key")
    assert isinstance(get_provider(), NullProvider)
    assert AMPPConfig().effective_provider == "null"


def test_no_lean_is_unavailable(monkeypatch, basic_candidate):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    passed, details = LeanVerifier().verify(proof_candidate(basic_candidate), {})
    assert not passed and details["outcome"] == "unavailable"


def test_success_requires_exact_statement_and_audit(monkeypatch, basic_candidate):
    passed, details = checker(monkeypatch).verify(proof_candidate(basic_candidate), {})
    assert passed
    assert details["statement"] == "2 + 2 = 4"
    assert "2 + 2 = 4" in details["lean_source"]
    assert "theorem ampp_claim" in details["lean_source"]
    assert details["axioms"] == []
    assert len(details["source_sha256"]) == 64


@pytest.mark.parametrize("output", ["", "compiled", "'other' does not depend on any axioms"])
def test_exit_zero_without_target_audit_is_not_proof(monkeypatch, basic_candidate, output):
    passed, details = checker(monkeypatch, output).verify(proof_candidate(basic_candidate), {})
    assert not passed and details["outcome"] == "inconclusive"


@pytest.mark.parametrize("axiom", ["sorryAx", "custom_axiom", "Lean.ofReduceBool"])
def test_compiled_admitted_or_custom_axiom_is_rejected(monkeypatch, basic_candidate, axiom):
    passed, details = checker(monkeypatch, f"'ampp_claim' depends on axioms: [{axiom}]").verify(
        proof_candidate(basic_candidate), {}
    )
    assert not passed and details["outcome"] == "failed"


def test_standard_axioms_recorded(monkeypatch, basic_candidate):
    passed, details = checker(
        monkeypatch, "'ampp_claim' depends on axioms: [propext, Classical.choice, Quot.sound]"
    ).verify(proof_candidate(basic_candidate), {})
    assert passed and len(details["axioms"]) == 3


@pytest.mark.parametrize(
    "proof",
    [
        "by sorry",
        "by admit",
        "by exact sorryAx _ false",
        "by native_decide",
        "by\n  trivial\n#print axioms ampp_claim",
        "by\n  trivial\n--",
        "by\n  trivial\n/-",
        'by trace "fake audit"',
    ],
)
def test_proof_escapes_rejected_before_compilation(monkeypatch, basic_candidate, proof):
    verifier = checker(monkeypatch)
    monkeypatch.setattr(
        verifier, "_compile", lambda _: pytest.fail("must reject before subprocess")
    )
    passed, details = verifier.verify(proof_candidate(basic_candidate, proof=proof), {})
    assert not passed and details["outcome"] == "failed"


def test_unrelated_legacy_true_theorem_not_accepted(monkeypatch, basic_candidate):
    passed, details = checker(monkeypatch).verify(basic_candidate, {})
    assert not passed and details["outcome"] == "inconclusive"


def test_compile_error_is_failure(monkeypatch, basic_candidate):
    passed, details = checker(monkeypatch, "type mismatch", 1).verify(
        proof_candidate(basic_candidate), {}
    )
    assert not passed and details["outcome"] == "failed"


def test_timeout_is_retryable_inconclusive(monkeypatch, basic_candidate):
    verifier = checker(monkeypatch)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("lean", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    passed, details = verifier.verify(proof_candidate(basic_candidate), {})
    assert not passed and details["outcome"] == "inconclusive"


def test_atp_does_not_prove_placeholder(basic_candidate):
    passed, details = ATPVerifier().verify(basic_candidate, {})
    assert not passed and details["outcome"] == "inconclusive"


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('echo bad') = 0",
        "x.__class__ = 0",
        "[x for x in range(5)] = 0",
        "x/x = 1",
        "n ** 100000 = 1",
        "True = 1",
        "2^3 = 8",
    ],
)
def test_arithmetic_parser_rejects_code_and_unsupported_forms(basic_candidate, text):
    candidate = proof_candidate(basic_candidate, text)
    for verifier in (SymPyVerifier(), Z3Verifier()):
        passed, details = verifier.verify(candidate, {})
        assert not passed and details["outcome"] == "inconclusive"


def test_sympy_never_executes_candidate_text(monkeypatch, basic_candidate):
    monkeypatch.setattr(os, "system", lambda _: pytest.fail("candidate executed Python"))
    passed, details = SymPyVerifier().verify(
        proof_candidate(basic_candidate, "__import__('os').system('anything') = 0"), {}
    )
    assert not passed and details["outcome"] == "inconclusive"


def test_z3_numeric_literals_are_not_variables(basic_candidate):
    assert Z3Verifier().verify(proof_candidate(basic_candidate, "3 >= 2"), {})[0]
    assert not Z3Verifier().verify(proof_candidate(basic_candidate, "3 < 2"), {})[0]


def test_candidate_success_criteria_cannot_create_vacuous_proof(basic_candidate):
    candidate = proof_candidate(basic_candidate, "n = 5")
    candidate.verification_plan.success_criteria = {"a": "n >= 1", "b": "n < 0"}
    passed, details = Z3Verifier().verify(candidate, {})
    assert not passed and details["outcome"] == "failed"


def test_z3_assumptions_positive_and_consistency_checked(basic_candidate):
    candidate = proof_candidate(basic_candidate, "n >= 0")
    assert Z3Verifier().verify(candidate, {"assumptions": ["n >= 1"]})[0]
    passed, details = Z3Verifier().verify(candidate, {"assumptions": ["n >= 1", "n < 0"]})
    assert not passed and details["outcome"] == "inconclusive"
    passed, details = Z3Verifier().verify(candidate, {"assumptions": ["unparseable"]})
    assert not passed and details["outcome"] == "inconclusive"


def test_v1_unknown_is_not_counterexample_and_finite_search_is_not_proof(basic_candidate):
    candidate = proof_candidate(basic_candidate, "A theorem in words")
    candidate.small_case_tests = [
        SmallCaseTest(description="unknown", parameters={"n": 1}, expected=True)
    ]
    passed, details = CounterexampleVerifier().verify(candidate, {})
    assert not passed and details["outcome"] == "inconclusive"
    assert "witness" not in details
    candidate = proof_candidate(basic_candidate, "n*n >= 0")
    passed, details = CounterexampleVerifier().verify(candidate, {})
    assert not passed and details["outcome"] == "inconclusive"


def test_v1_computes_real_witness(basic_candidate):
    candidate = proof_candidate(basic_candidate, "n*n = n")
    candidate.verification_plan.enumeration_bound = 5
    passed, details = CounterexampleVerifier().verify(candidate, {})
    assert not passed and details["outcome"] == "failed"
    assert details["witness"] == {"n": 2}


@pytest.mark.parametrize("payload", [None, [], 1, {"stage": []}, {"stage": "V5", "context": []}])
def test_worker_invalid_envelopes_fail_closed(payload):
    response = handle(payload)
    assert not response["passed"]
    assert response["details"]["outcome"] == "error"


def test_worker_recovers_from_bad_json_and_nonobject_input():
    proc = subprocess.run(
        [sys.executable, "-m", "ampp.worker"],
        input='bad-json\n[]\n{"stage":"PING","request_id":"ready"}\n{"type":"shutdown"}\n',
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "AMPP_LLM_PROVIDER": "null"},
    )
    assert proc.returncode == 0, proc.stderr
    messages = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r["passed"] for r in messages] == [False, False, True]
    assert messages[-1]["request_id"] == "ready"
    assert "python" in messages[-1]["details"]["versions"]


def test_formal_proposer_cannot_change_target():
    class FakeProvider(LLMProvider):
        def complete(self, *args, **kwargs):
            return json.dumps({"statement": "True", "proof": "by decide"})

    set_provider(FakeProvider())
    try:
        candidates = FormalProofProposer().propose(
            "sg", "b", {"formal_target": True, "target": "2 + 2 = 4"}, [], []
        )
        assert candidates[0].new_claims[0].statement == "2 + 2 = 4"
        assert candidates[0].lean_stub == "by decide"
    finally:
        set_provider(None)


def test_real_lean_checks_claim_and_rejects_wrong_proof(basic_candidate):
    if shutil.which(cfg.lean_binary) is None:
        pytest.skip("Lean not installed; CI integration installs the pinned toolchain")
    verifier = LeanVerifier()
    passed, details = verifier.verify(proof_candidate(basic_candidate), {})
    assert passed, details
    assert details["lean_result"] == "compiled"
    passed, details = verifier.verify(proof_candidate(basic_candidate, "2 + 2 = 5"), {})
    assert not passed and details["outcome"] == "failed"
    passed, details = verifier.verify(proof_candidate(basic_candidate, "False", "by trivial"), {})
    assert not passed and details["outcome"] == "failed"


def test_rubric_does_not_count_same_persisted_attempt_twice_or_penalize_unavailable():
    from ampp.agents.rubric_agent import RubricAgent

    rubric = RubricAgent()
    attempts = [
        {"id": "a", "verifier_stage": "V5_LEAN", "raw_output": {"outcome": "rejected"}},
        {"id": "b", "verifier_stage": "V5_LEAN", "raw_output": {"outcome": "unverified"}},
        {"id": "c", "verifier_stage": "V5_LEAN", "raw_output": {"outcome": "error"}},
    ]
    rubric._update_failure_counts(attempts)
    rubric._update_failure_counts(attempts)
    assert rubric._failure_counts == {"V5_LEAN": 1}
    assert rubric._total_attempts == 1


@pytest.mark.parametrize("value", ["[]", "null", '"text"', "42"])
def test_llm_json_requires_object(value):
    class FakeProvider(LLMProvider):
        def complete(self, *args, **kwargs):
            return value

    assert FakeProvider().complete_json("system", "user") is None


@pytest.mark.parametrize(
    "field", ["lean_timeout_sec", "z3_timeout_ms", "llm_retries", "llm_max_tokens"]
)
def test_zero_deadlines_and_budgets_are_invalid(field):
    with pytest.raises(ValueError, match="positive"):
        AMPPConfig(**{field: 0})
