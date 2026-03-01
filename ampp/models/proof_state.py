"""
ProofState — append-only, versioned container for all proof objects.

State transitions are tracked and hashed for full reproducibility.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ampp.models.state import (
    Attempt,
    Claim,
    Counterexample,
    Definition,
    FormalSpec,
    Subgoal,
)


@dataclass
class ProofState:
    """
    The central append-only proof state.

    Every mutation returns a new version number. Old versions can be
    reconstructed from the versioned log.
    """

    # ── Core Collections ──────────────────────────────────────────────
    formal_spec: FormalSpec | None = None
    definitions: dict[str, Definition] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    subgoals: dict[str, Subgoal] = field(default_factory=dict)
    counterexamples: list[Counterexample] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)

    # ── Version Tracking ──────────────────────────────────────────────
    version: int = 0
    version_log: list[dict[str, Any]] = field(default_factory=list)
    branch_id: str = "main"

    # ── Timestamps ────────────────────────────────────────────────────
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    # ─────────────────────────────────────────────────────────────────
    # Mutation helpers (produce new version)
    # ─────────────────────────────────────────────────────────────────

    def _bump(self, action: str, detail: str = "") -> int:
        self.version += 1
        entry = {
            "version": self.version,
            "action": action,
            "detail": detail,
            "timestamp": datetime.now(UTC).isoformat(),
            "branch": self.branch_id,
        }
        self.version_log.append(entry)
        return self.version

    # ── Definitions ───────────────────────────────────────────────────

    def add_definition(self, defn: Definition) -> int:
        self.definitions[defn.id] = defn
        return self._bump("add_definition", defn.id)

    # ── Claims ────────────────────────────────────────────────────────

    def add_claim(self, claim: Claim) -> int:
        self.claims[claim.id] = claim
        return self._bump("add_claim", f"{claim.id} ({claim.claim_type})")

    def update_claim(self, claim: Claim) -> int:
        old = self.claims.get(claim.id)
        if old and old.status == "rejected":
            raise ValueError(
                f"Cannot update rejected claim {claim.id}"
            )
        self.claims[claim.id] = claim
        return self._bump("update_claim", f"{claim.id} → {claim.status}")

    def verify_claim(self, claim_id: str) -> int:
        claim = self.claims[claim_id]
        updated = claim.with_status("verified")
        self.claims[claim_id] = updated
        return self._bump("verify_claim", claim_id)

    def reject_claim(self, claim_id: str, reason: str = "") -> int:
        claim = self.claims[claim_id]
        updated = claim.with_status("rejected")
        self.claims[claim_id] = updated
        return self._bump("reject_claim", f"{claim_id}: {reason}")

    # ── Subgoals ──────────────────────────────────────────────────────

    def add_subgoal(self, sg: Subgoal) -> int:
        self.subgoals[sg.id] = sg
        return self._bump("add_subgoal", sg.id)

    def resolve_subgoal(self, sg_id: str) -> int:
        sg = self.subgoals[sg_id]
        # Create new resolved subgoal
        resolved = Subgoal(
            id=sg.id,
            target_claim=sg.target_claim,
            statement=sg.statement,
            priority_score=sg.priority_score,
            difficulty_estimate=sg.difficulty_estimate,
            blockers=sg.blockers,
            expected_strategy=sg.expected_strategy,
            verification_plan=sg.verification_plan,
            resolved=True,
        )
        self.subgoals[sg_id] = resolved
        return self._bump("resolve_subgoal", sg_id)

    # ── Counterexamples ───────────────────────────────────────────────

    def add_counterexample(self, cx: Counterexample) -> int:
        self.counterexamples.append(cx)
        return self._bump("add_counterexample", f"claim={cx.claim_id}")

    # ── Attempts ──────────────────────────────────────────────────────

    def add_attempt(self, att: Attempt) -> int:
        self.attempts.append(att)
        return self._bump("add_attempt", f"claim={att.failed_claim}")

    # ─────────────────────────────────────────────────────────────────
    # Queries
    # ─────────────────────────────────────────────────────────────────

    @property
    def verified_claims(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.is_verified]

    @property
    def proposed_claims(self) -> list[Claim]:
        return [
            c for c in self.claims.values() if c.status == "proposed"
        ]

    @property
    def rejected_claims(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.is_rejected]

    @property
    def open_subgoals(self) -> list[Subgoal]:
        return [
            sg for sg in self.subgoals.values() if not sg.resolved
        ]

    @property
    def verified_claim_ids(self) -> set[str]:
        return {c.id for c in self.verified_claims}

    def has_verified_theorem(self) -> bool:
        return any(
            c.claim_type == "theorem" and c.is_verified
            for c in self.claims.values()
        )

    def dependencies_satisfied(self, claim: Claim) -> bool:
        verified = self.verified_claim_ids
        return all(d in verified for d in claim.dependencies)

    def failure_modes(self) -> dict[str, int]:
        """Count failure reasons by verifier stage."""
        counts: dict[str, int] = {}
        for att in self.attempts:
            key = att.verifier_stage
            counts[key] = counts.get(key, 0) + 1
        return counts

    def claim_hashes(self) -> set[str]:
        """All hashes of previously attempted claims (for non-repetition)."""
        hashes: set[str] = set()
        for att in self.attempts:
            if att.claim_hash:
                hashes.add(att.claim_hash)
        for c in self.claims.values():
            if c.proof_hash:
                hashes.add(c.proof_hash)
        return hashes

    # ─────────────────────────────────────────────────────────────────
    # Snapshot / Clone
    # ─────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Serializable snapshot of the current state."""
        return {
            "version": self.version,
            "branch_id": self.branch_id,
            "verified_count": len(self.verified_claims),
            "proposed_count": len(self.proposed_claims),
            "rejected_count": len(self.rejected_claims),
            "open_subgoals": len(self.open_subgoals),
            "counterexamples": len(self.counterexamples),
            "attempts": len(self.attempts),
        }

    def clone(self, new_branch_id: str | None = None) -> ProofState:
        """Deep copy the state for beam branching."""
        cloned = copy.deepcopy(self)
        if new_branch_id:
            cloned.branch_id = new_branch_id
        return cloned

    def state_hash(self) -> str:
        """Deterministic hash of the current state for reproducibility."""
        data = json.dumps(
            {
                "verified": sorted(c.id for c in self.verified_claims),
                "open_subgoals": sorted(
                    sg.id for sg in self.open_subgoals
                ),
                "version": self.version,
            },
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]
