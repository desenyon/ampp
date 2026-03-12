"""Shared pytest fixtures."""
from __future__ import annotations

import hashlib
import uuid

import pytest

from ampp.schemas import (
    ActionType,
    NewClaimSpec,
    SmallCaseTest,
    StepCandidate,
    StrategyFamily,
    VerificationPlan,
)


@pytest.fixture
def basic_candidate() -> StepCandidate:
    """A minimal valid StepCandidate for use in multiple tests."""
    return StepCandidate(
        id=str(uuid.uuid4()),
        subgoal_id="sg-fixture",
        action_type=ActionType.INTRODUCE_LEMMA,
        new_claims=[NewClaimSpec(statement="For all n >= 1, the property holds")],
        dependencies=[],
        verification_plan=VerificationPlan(
            stages=["V0", "V1", "V5"],
            success_criteria={"V5": "lean compiles"},
        ),
        small_case_tests=[
            SmallCaseTest(description="n=1", parameters={"n": 1}, expected=True),
            SmallCaseTest(description="n=2", parameters={"n": 2}, expected=True),
        ],
        lean_stub="theorem lemma_fix : True := trivial",
        strategy_family=StrategyFamily.INDUCTION,
        candidate_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        branch_id="branch-fixture",
    )


@pytest.fixture
def sample_spec() -> dict:
    return {
        "raw_statement": "For all n in N, n*(n+1) is even",
        "canonical_statement": "for all n in N, n*(n+1) is even",
        "target": "for all n in N, n*(n+1) is even",
        "variables": {"n": "N"},
        "quantifiers": [{"quantifier": "forall", "variable": "n", "domain": "N"}],
        "constraints": ["n >= 0"],
        "edge_cases": ["n=0", "n=1"],
        "lean_namespace": "ForAllEven",
    }
