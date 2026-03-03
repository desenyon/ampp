"""Pydantic schemas mirroring the Rust state model.

All objects must be serialisable to/from JSON without loss to satisfy
the deterministic IPC contract with the Rust core.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, field_validator


# ── Enumerations ──────────────────────────────────────────────────────────────

class ActionType(str, Enum):
    INTRODUCE_LEMMA = "introduce_lemma"
    APPLY_INDUCTION = "apply_induction"
    CONSTRUCT_WITNESS = "construct_witness"
    CASE_SPLIT = "case_split"
    APPLY_TRANSFORM = "apply_transform"
    REFUTE_BY_COUNTEREXAMPLE = "refute_by_counterexample"
    MINE_CONJECTURE = "mine_conjecture"


class StrategyFamily(str, Enum):
    INDUCTION = "induction"
    STRONG_INDUCTION = "strong_induction"
    MINIMAL_COUNTEREXAMPLE = "minimal_counterexample"
    EXTREMAL_PRINCIPLE = "extremal_principle"
    INVARIANT_MONOVARIANT = "invariant_monovariant"
    ALGEBRAIC_NORMALIZATION = "algebraic_normalization"
    DOUBLE_COUNTING = "double_counting"
    CONSTRUCTIVE = "constructive"
    GRAPH_TRANSLATION = "graph_translation"
    CONTRADICTION = "contradiction"


class ClaimType(str, Enum):
    LEMMA = "lemma"
    THEOREM = "theorem"
    AUXILIARY = "auxiliary"
    DEFINITION = "definition"


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"


# ── Core objects ──────────────────────────────────────────────────────────────

class VerificationPlan(BaseModel):
    stages: list[str]
    success_criteria: dict[str, str] = {}
    enumeration_bound: int | None = None

    @field_validator("stages")
    @classmethod
    def stages_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("verification_plan.stages must not be empty")
        return v


class SmallCaseTest(BaseModel):
    description: str
    parameters: dict[str, Any]
    expected: bool


class NewClaimSpec(BaseModel):
    statement: str
    claim_type: str = "lemma"

    @field_validator("statement")
    @classmethod
    def statement_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("claim statement must not be empty")
        return v


class StepCandidate(BaseModel):
    """Structured proof-step candidate produced by a Proposer.

    All fields are mandatory; validation raises ValidationError otherwise.
    """
    id: str
    subgoal_id: str
    action_type: ActionType
    new_claims: list[NewClaimSpec]
    dependencies: list[str] = []
    verification_plan: VerificationPlan
    small_case_tests: list[SmallCaseTest] = []
    lean_stub: str
    strategy_family: StrategyFamily
    candidate_hash: str
    branch_id: str

    @field_validator("new_claims")
    @classmethod
    def at_least_one_claim(cls, v: list[NewClaimSpec]) -> list[NewClaimSpec]:
        if not v:
            raise ValueError("new_claims must not be empty")
        return v

    @field_validator("lean_stub")
    @classmethod
    def lean_stub_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("lean_stub must not be empty")
        return v


class VerificationRequest(BaseModel):
    request_id: str
    stage: str
    candidate_json: dict[str, Any]
    context: dict[str, Any]


class VerificationResponse(BaseModel):
    request_id: str
    stage: str
    passed: bool
    details: dict[str, Any] = {}
    counterexample: dict[str, Any] | None = None


class FormalSpec(BaseModel):
    """Normalised problem specification."""
    raw_statement: str
    canonical_statement: str
    variables: dict[str, str] = {}
    quantifiers: list[dict[str, Any]] = []
    constraints: list[str] = []
    target: str
    edge_cases: list[str] = []
    lean_namespace: str = "AMPP"

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint based on the canonical statement."""
        payload = json.dumps(
            {
                "canonical_statement": self.canonical_statement,
                "target": self.target,
                "constraints": sorted(self.constraints),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
