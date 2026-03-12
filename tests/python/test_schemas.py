"""Tests for Pydantic schemas — exhaustive validation coverage."""
from __future__ import annotations

import hashlib
import uuid

import pytest
from pydantic import ValidationError

from ampp.schemas import (
    ActionType,
    FormalSpec,
    NewClaimSpec,
    SmallCaseTest,
    StepCandidate,
    StrategyFamily,
    VerificationPlan,
)


def make_candidate(**overrides) -> StepCandidate:
    defaults = {
        "id": str(uuid.uuid4()),
        "subgoal_id": "sg-1",
        "action_type": ActionType.INTRODUCE_LEMMA,
        "new_claims": [NewClaimSpec(statement="2 + 2 = 4")],
        "dependencies": [],
        "verification_plan": VerificationPlan(stages=["V0", "V1", "V5"]),
        "small_case_tests": [],
        "lean_stub": "theorem t : 2 + 2 = 4 := by norm_num",
        "strategy_family": StrategyFamily.ALGEBRAIC_NORMALIZATION,
        "candidate_hash": hashlib.sha256(b"test").hexdigest(),
        "branch_id": "branch-1",
    }
    defaults.update(overrides)
    return StepCandidate(**defaults)


class TestNewClaimSpec:
    def test_valid(self):
        c = NewClaimSpec(statement="n >= 0")
        assert c.statement == "n >= 0"

    def test_empty_statement_raises(self):
        with pytest.raises(ValidationError, match="empty"):
            NewClaimSpec(statement="   ")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError):
            NewClaimSpec(statement="\t\n")


class TestVerificationPlan:
    def test_valid(self):
        vp = VerificationPlan(stages=["V0", "V5"])
        assert len(vp.stages) == 2

    def test_empty_stages_raises(self):
        with pytest.raises(ValidationError, match="empty"):
            VerificationPlan(stages=[])

    def test_enumeration_bound_optional(self):
        vp = VerificationPlan(stages=["V1"], enumeration_bound=100)
        assert vp.enumeration_bound == 100


class TestStepCandidate:
    def test_valid_construction(self):
        c = make_candidate()
        assert c.branch_id == "branch-1"
        assert c.action_type == ActionType.INTRODUCE_LEMMA

    def test_empty_new_claims_raises(self):
        with pytest.raises(ValidationError, match="empty"):
            make_candidate(new_claims=[])

    def test_empty_lean_stub_raises(self):
        with pytest.raises(ValidationError, match="empty"):
            make_candidate(lean_stub="   ")

    def test_action_type_enum(self):
        for at in ActionType:
            c = make_candidate(action_type=at)
            assert c.action_type == at

    def test_strategy_family_enum(self):
        for sf in StrategyFamily:
            c = make_candidate(strategy_family=sf)
            assert c.strategy_family == sf

    def test_serialise_roundtrip(self):
        c = make_candidate()
        data = c.model_dump()
        c2 = StepCandidate.model_validate(data)
        assert c2.id == c.id
        assert c2.candidate_hash == c.candidate_hash

    def test_json_roundtrip(self):
        c = make_candidate()
        json_str = c.model_dump_json()
        c2 = StepCandidate.model_validate_json(json_str)
        assert c2.subgoal_id == c.subgoal_id


class TestFormalSpec:
    def test_valid(self):
        spec = FormalSpec(
            raw_statement="For all n in N, n >= 0",
            canonical_statement="for all n in N, n >= 0",
            target="for all n in N, n >= 0",
        )
        assert spec.lean_namespace == "AMPP"

    def test_fingerprint_deterministic(self):
        spec = FormalSpec(
            raw_statement="test",
            canonical_statement="test",
            target="test",
        )
        assert spec.fingerprint() == spec.fingerprint()

    def test_fingerprint_differs_on_different_statement(self):
        spec1 = FormalSpec(raw_statement="a", canonical_statement="a", target="a")
        spec2 = FormalSpec(raw_statement="b", canonical_statement="b", target="b")
        assert spec1.fingerprint() != spec2.fingerprint()


class TestSmallCaseTest:
    def test_valid(self):
        t = SmallCaseTest(description="n=0", parameters={"n": 0}, expected=True)
        assert t.expected is True

    def test_false_expected(self):
        t = SmallCaseTest(
            description="should fail", parameters={"n": -1}, expected=False
        )
        assert t.expected is False
