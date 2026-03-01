"""
Core state objects for the AMPP pipeline.

All state objects are immutable dataclasses. The proof state is append-only
and versioned — mutations produce new versions.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _hash_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# ── Formal Specification ──────────────────────────────────────────────────


@dataclass(frozen=True)
class VariableDecl:
    """A variable declaration with its domain."""
    name: str
    domain: str  # e.g., "ℕ", "ℤ", "ℝ", "Fin n", "Set α"
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class FormalSpec:
    """
    Structured formal specification of a problem.
    Produced by the normalizer, consumed by all downstream components.
    """
    problem_id: str
    raw_statement: str
    variables: tuple[VariableDecl, ...]
    quantifiers: tuple[str, ...]  # e.g., ("∀ n : ℕ", "∃ k : ℕ")
    constraints: tuple[str, ...]
    target_statement: str
    canonical_form: str
    edge_cases: tuple[str, ...] = ()
    hash: str = ""

    def __post_init__(self) -> None:
        if not self.hash:
            h = _hash_str(self.canonical_form)
            object.__setattr__(self, "hash", h)


# ── Definition ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Definition:
    """
    A mathematical definition registered in the proof state.
    """
    id: str = field(default_factory=_new_id)
    statement: str = ""
    canonical_form: str = ""
    lean_name: str = ""
    hash: str = ""

    def __post_init__(self) -> None:
        if not self.hash and self.canonical_form:
            object.__setattr__(self, "hash", _hash_str(self.canonical_form))


# ── Claim ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerificationArtifact:
    """Record of a single verification check."""
    stage: str          # V0..V5
    result: str         # "pass", "fail", "skip", "timeout"
    details: str = ""
    log_path: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class Claim:
    """
    A mathematical claim (lemma, theorem, or auxiliary).
    Status transitions: proposed → verified | rejected
    Rejected claims are immutable.
    """
    id: str = field(default_factory=_new_id)
    statement: str = ""
    claim_type: str = "lemma"        # lemma | theorem | auxiliary
    status: str = "proposed"         # proposed | verified | rejected
    dependencies: tuple[str, ...] = ()
    verification_artifacts: tuple[VerificationArtifact, ...] = ()
    proof_hash: str = ""
    lean_code: str = ""
    strategy_family: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def with_status(self, status: str) -> Claim:
        return Claim(
            id=self.id,
            statement=self.statement,
            claim_type=self.claim_type,
            status=status,
            dependencies=self.dependencies,
            verification_artifacts=self.verification_artifacts,
            proof_hash=self.proof_hash,
            lean_code=self.lean_code,
            strategy_family=self.strategy_family,
            created_at=self.created_at,
        )

    def with_artifacts(
        self, artifacts: tuple[VerificationArtifact, ...]
    ) -> Claim:
        return Claim(
            id=self.id,
            statement=self.statement,
            claim_type=self.claim_type,
            status=self.status,
            dependencies=self.dependencies,
            verification_artifacts=artifacts,
            proof_hash=self.proof_hash,
            lean_code=self.lean_code,
            strategy_family=self.strategy_family,
            created_at=self.created_at,
        )

    @property
    def is_verified(self) -> bool:
        return self.status == "verified"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"


# ── Subgoal ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Subgoal:
    """
    A subgoal in the proof plan DAG.
    """
    id: str = field(default_factory=_new_id)
    target_claim: str = ""           # Claim ID
    statement: str = ""
    priority_score: float = 0.0
    difficulty_estimate: float = 1.0
    blockers: tuple[str, ...] = ()   # Claim IDs that must be verified first
    expected_strategy: str = ""
    verification_plan: str = ""
    resolved: bool = False

    @property
    def effective_priority(self) -> float:
        if self.difficulty_estimate <= 0:
            return float("inf")
        return self.priority_score / self.difficulty_estimate


# ── Counterexample ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Counterexample:
    """
    A counterexample witness that disproves a claim.
    """
    id: str = field(default_factory=_new_id)
    claim_id: str = ""
    witness_structure: dict[str, Any] = field(default_factory=dict)
    generation_method: str = ""    # "exhaustive", "random", "boundary", "z3"
    seed: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    @property
    def witness_json(self) -> str:
        return json.dumps(self.witness_structure, sort_keys=True)


# ── Attempt ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Attempt:
    """
    Record of a failed proof attempt. Used for failure-pattern tracking
    and non-repetition enforcement.
    """
    id: str = field(default_factory=_new_id)
    branch_id: str = ""
    failed_claim: str = ""           # Claim ID
    failure_reason: str = ""
    verifier_stage: str = ""         # V0..V5
    strategy_used: str = ""
    claim_hash: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
