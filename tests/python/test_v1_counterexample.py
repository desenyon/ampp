"""Tests for V1 counterexample verifier."""
from __future__ import annotations

import hashlib
import uuid


from ampp.schemas import (
    ActionType,
    NewClaimSpec,
    SmallCaseTest,
    StepCandidate,
    StrategyFamily,
    VerificationPlan,
)
from ampp.verifiers.v1_counterexample import CounterexampleVerifier


def _candidate(
    stages: list[str] | None = None,
    small_cases: list[SmallCaseTest] | None = None,
    bound: int | None = None,
) -> StepCandidate:
    return StepCandidate(
        id=str(uuid.uuid4()),
        subgoal_id="sg-cx",
        action_type=ActionType.INTRODUCE_LEMMA,
        new_claims=[NewClaimSpec(statement="n >= 0 for all n in N")],
        dependencies=[],
        verification_plan=VerificationPlan(
            stages=stages or ["V0", "V1", "V5"],
            enumeration_bound=bound,
        ),
        small_case_tests=small_cases or [],
        lean_stub="-- stub",
        strategy_family=StrategyFamily.INDUCTION,
        candidate_hash=hashlib.sha256(b"cx-test").hexdigest(),
        branch_id="branch-cx",
    )


class TestCounterexampleVerifier:
    def setup_method(self):
        self.verifier = CounterexampleVerifier(seed=42)

    def test_trivial_claim_passes(self):
        cand = _candidate()
        passed, details = self.verifier.verify(cand, {})
        assert passed is True

    def test_passing_small_case_test(self):
        cases = [SmallCaseTest(description="n=0", parameters={"n": 0}, expected=True)]
        cand = _candidate(small_cases=cases)
        passed, details = self.verifier.verify(cand, {})
        assert passed is True

    def test_small_case_failure_detected(self):
        """Override _evaluate_claim to return False for one test."""
        class FailingVerifier(CounterexampleVerifier):
            def _evaluate_claim(self, candidate, params):
                return params.get("n") != 0  # fails for n=0

        verifier = FailingVerifier(seed=42)
        cases = [SmallCaseTest(description="n=0", parameters={"n": 0}, expected=True)]
        cand = _candidate(small_cases=cases)
        passed, details = verifier.verify(cand, {})
        assert passed is False
        assert "witness" in details

    def test_exhaustive_check_with_bound(self):
        cand = _candidate(stages=["V0", "V1"], bound=50)
        passed, details = self.verifier.verify(cand, {})
        assert passed is True  # default evaluator returns True

    def test_exhaustive_finds_counterexample(self):
        class CxVerifier(CounterexampleVerifier):
            def _evaluate_claim(self, candidate, params):
                return params.get("n", 0) != 7  # fails for n=7

        verifier = CxVerifier(seed=42)
        cand = _candidate(bound=10)
        passed, details = verifier.verify(cand, {})
        assert passed is False
        assert details.get("witness", {}).get("n") == 7

    def test_seed_reproducibility(self):
        """Two verifiers with same seed should produce same random tests."""
        v1 = CounterexampleVerifier(seed=99)
        v2 = CounterexampleVerifier(seed=99)
        cand = _candidate()
        r1 = v1.verify(cand, {})
        r2 = v2.verify(cand, {})
        assert r1[0] == r2[0]
