"""Tests for V2 SymPy symbolic verifier."""
from __future__ import annotations

import hashlib
import uuid

import pytest

from ampp.schemas import (
    ActionType,
    NewClaimSpec,
    StepCandidate,
    StrategyFamily,
    VerificationPlan,
)
from ampp.verifiers.v2_sympy import SymPyVerifier

pytest.importorskip("sympy")


def _candidate(statement: str) -> StepCandidate:
    return StepCandidate(
        id=str(uuid.uuid4()),
        subgoal_id="sg-sympy",
        action_type=ActionType.APPLY_TRANSFORM,
        new_claims=[NewClaimSpec(statement=statement)],
        dependencies=[],
        verification_plan=VerificationPlan(stages=["V0", "V2", "V5"]),
        small_case_tests=[],
        lean_stub="-- stub",
        strategy_family=StrategyFamily.ALGEBRAIC_NORMALIZATION,
        candidate_hash=hashlib.sha256(statement.encode()).hexdigest(),
        branch_id="branch-sympy",
    )


class TestSymPyVerifier:
    def setup_method(self):
        self.verifier = SymPyVerifier()

    def test_true_identity_passes(self):
        cand = _candidate("2 + 2 = 4")
        passed, _ = self.verifier.verify(cand, {})
        assert passed is True

    def test_false_identity_fails(self):
        cand = _candidate("2 + 2 = 5")
        passed, details = self.verifier.verify(cand, {})
        assert passed is False
        assert "SymPy refuted" in details.get("reason", "")

    def test_symbolic_identity_passes(self):
        # x + x = 2*x
        cand = _candidate("x + x = 2*x")
        passed, _ = self.verifier.verify(cand, {})
        assert passed is True

    def test_true_inequality_passes(self):
        cand = _candidate("3 >= 2")
        passed, _ = self.verifier.verify(cand, {})
        assert passed is True

    def test_false_inequality_fails(self):
        cand = _candidate("1 >= 5")
        passed, details = self.verifier.verify(cand, {})
        assert passed is False

    def test_undecidable_symbolic_passes_conservatively(self):
        # A statement that can't be simplified to True/False
        cand = _candidate("some complex math statement that sympy cannot parse")
        passed, _ = self.verifier.verify(cand, {})
        # Conservative: undecidable → pass
        assert passed is True

    def test_multiple_claims_all_must_pass(self):
        from ampp.schemas import StepCandidate
        cand = StepCandidate(
            id=str(uuid.uuid4()),
            subgoal_id="sg-sympy",
            action_type=ActionType.APPLY_TRANSFORM,
            new_claims=[
                NewClaimSpec(statement="2 + 2 = 4"),
                NewClaimSpec(statement="1 + 1 = 3"),  # false
            ],
            dependencies=[],
            verification_plan=VerificationPlan(stages=["V2"]),
            small_case_tests=[],
            lean_stub="-- stub",
            strategy_family=StrategyFamily.ALGEBRAIC_NORMALIZATION,
            candidate_hash="multi",
            branch_id="branch-1",
        )
        passed, _ = self.verifier.verify(cand, {})
        assert passed is False
