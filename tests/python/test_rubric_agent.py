"""Tests for the Rubric Agent — quality gate and workflow controller."""
from __future__ import annotations

import hashlib
import uuid

import pytest

from ampp.agents.rubric_agent import RubricAgent, PASS_THRESHOLD, RubricScore
from ampp.schemas import (
    ActionType,
    NewClaimSpec,
    SmallCaseTest,
    StepCandidate,
    StrategyFamily,
    VerificationPlan,
)


def make_good_candidate(branch_id: str = "b1") -> StepCandidate:
    return StepCandidate(
        id=str(uuid.uuid4()),
        subgoal_id="sg-1",
        action_type=ActionType.INTRODUCE_LEMMA,
        new_claims=[NewClaimSpec(statement="For all n >= 1, the property holds")],
        dependencies=[],
        verification_plan=VerificationPlan(
            stages=["V0", "V1", "V5"],
            success_criteria={"V5": "lean compiles"},
        ),
        small_case_tests=[
            SmallCaseTest(description="n=1", parameters={"n": 1}, expected=True)
        ],
        lean_stub="theorem t : True := trivial",
        strategy_family=StrategyFamily.INDUCTION,
        candidate_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        branch_id=branch_id,
    )


def make_bad_candidate_no_stages() -> StepCandidate:
    """Candidate with empty stages (should fail checkability gate)."""
    # We have to bypass pydantic validation by patching after creation
    good = make_good_candidate()
    # Manually patch the plan (bypassing validator for testing the rubric)
    object.__setattr__(
        good.verification_plan,
        "stages",
        [],
    )
    return good


class TestRubricAgent:
    def setup_method(self):
        self.agent = RubricAgent()

    def test_good_candidate_passes(self):
        cand = make_good_candidate()
        results = self.agent.triage([cand], [])
        assert len(results) == 1
        assert results[0].id == cand.id

    def test_too_many_claims_fails_locality(self):
        cand = make_good_candidate()
        # Add many claims to exceed locality threshold
        extra_claims = [NewClaimSpec(statement=f"claim {i}") for i in range(10)]
        patched = cand.model_copy(update={"new_claims": extra_claims})
        results = self.agent.triage([patched], [])
        assert len(results) == 0

    def test_duplicate_hash_rejected(self):
        cand = make_good_candidate()
        # Triage once  — accepted
        results1 = self.agent.triage([cand], [])
        assert len(results1) == 1

        # Simulate rejection by adding hash to rejected set
        self.agent._rejected_hashes.add(cand.candidate_hash)

        # Triage again — should be rejected
        results2 = self.agent.triage([cand], [])
        assert len(results2) == 0

    def test_multiple_candidates_ranked_by_score(self):
        c1 = make_good_candidate()
        c2 = make_good_candidate()
        # c2 gets more points via a shorter statement
        short_claims = [NewClaimSpec(statement="n >= 0")]
        c2 = c2.model_copy(update={"new_claims": short_claims, "id": str(uuid.uuid4())})
        results = self.agent.triage([c1, c2], [])
        assert len(results) == 2

    def test_postmortem_returns_weights(self):
        attempts = [
            {"verifier_stage": "V5_LEAN", "failure_reason": "Lean failed"},
        ] * 6
        weights = self.agent.postmortem(attempts)
        assert isinstance(weights, dict)
        assert all(isinstance(v, float) for v in weights.values())

    def test_validate_termination_blocks_incomplete(self):
        assert not self.agent.validate_termination({})
        assert not self.agent.validate_termination({"theorem_verified": False})

    def test_validate_termination_allows_verified(self):
        assert self.agent.validate_termination({"theorem_verified": True})

    def test_validate_termination_allows_explicit_incomplete(self):
        assert self.agent.validate_termination(
            {"explicit_incomplete": True, "artifacts_complete": True}
        )

    def test_failure_pattern_tracking(self):
        attempts = [
            {"verifier_stage": "V1_COUNTEREXAMPLE"},
            {"verifier_stage": "V1_COUNTEREXAMPLE"},
            {"verifier_stage": "V3_SMT"},
        ]
        self.agent._update_failure_counts(attempts)
        assert self.agent._failure_counts["V1_COUNTEREXAMPLE"] == 2
        assert self.agent._failure_counts["V3_SMT"] == 1
