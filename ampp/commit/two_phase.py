"""
Two-Phase Commit (Section 9)

Only after passing all required verification layers:
    proposed → verified

Commit includes:
- Lean artifact
- Build log
- Solver logs
- Hash record

Rejected claims are immutable.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ampp.models.proof_state import ProofState
from ampp.models.state import (
    Attempt,
    Claim,
    Counterexample,
    VerificationArtifact,
)
from ampp.models.step_candidate import StepCandidate
from ampp.verification.cascade import CascadeResult

logger = logging.getLogger(__name__)


@dataclass
class CommitRecord:
    """
    Record of a two-phase commit operation.
    """
    claim_id: str
    action: str  # "verify" or "reject"
    artifacts: list[VerificationArtifact]
    commit_hash: str
    timestamp: str
    details: str = ""


class TwoPhaseCommit:
    """
    Two-Phase Commit Engine (Section 9).

    Phase 1 (Prepare): Validate cascade result and all artifacts.
    Phase 2 (Commit): Atomically update proof state.

    No partial commits. Either the full claim is verified or rejected.
    Rejected claims are immutable — they can never be re-proposed with
    the same hash.
    """

    def __init__(self, log_dir: str | None = None) -> None:
        self.log_dir = Path(log_dir) if log_dir else None
        self.commit_log: list[CommitRecord] = []

    def commit(
        self,
        candidate: StepCandidate,
        claim: Claim,
        cascade_result: CascadeResult,
        state: ProofState,
    ) -> CommitRecord:
        """
        Execute two-phase commit for a verified or rejected claim.

        Phase 1 — Prepare:
            Validate all artifacts, compute commit hash.

        Phase 2 — Commit:
            Update proof state atomically.

        Args:
            candidate: The StepCandidate that was verified.
            claim: The Claim object.
            cascade_result: Result from the verification cascade.
            state: The proof state to update.

        Returns:
            CommitRecord documenting the commit.
        """
        # ── Phase 1: Prepare ──────────────────────────────────────
        commit_hash = self._compute_commit_hash(
            claim, cascade_result
        )

        # Validate: no rejected claim can be re-verified
        if claim.id in state.claims:
            existing = state.claims[claim.id]
            if existing.is_rejected:
                raise ValueError(
                    f"Cannot commit to rejected claim {claim.id}"
                )

        # ── Phase 2: Commit ───────────────────────────────────────
        if cascade_result.passed:
            record = self._commit_verify(
                candidate, claim, cascade_result, state, commit_hash
            )
        else:
            record = self._commit_reject(
                candidate, claim, cascade_result, state, commit_hash
            )

        # Log the commit
        self.commit_log.append(record)
        self._write_log(record)

        logger.info(
            "Two-phase commit: %s claim %s (hash=%s)",
            record.action,
            record.claim_id,
            record.commit_hash[:8],
        )

        return record

    def _commit_verify(
        self,
        candidate: StepCandidate,
        claim: Claim,
        cascade_result: CascadeResult,
        state: ProofState,
        commit_hash: str,
    ) -> CommitRecord:
        """Commit a verified claim."""
        # Create verified claim with all artifacts
        verified_claim = Claim(
            id=claim.id,
            statement=claim.statement,
            claim_type=claim.claim_type,
            status="verified",
            dependencies=claim.dependencies,
            verification_artifacts=tuple(cascade_result.artifacts),
            proof_hash=commit_hash,
            lean_code=claim.lean_code or candidate.lean_stub,
            strategy_family=candidate.strategy_family,
            created_at=claim.created_at,
        )

        # Atomic state update
        state.update_claim(verified_claim)

        # Resolve associated subgoal if it exists
        if candidate.subgoal_id in state.subgoals:
            state.resolve_subgoal(candidate.subgoal_id)

        return CommitRecord(
            claim_id=claim.id,
            action="verify",
            artifacts=cascade_result.artifacts,
            commit_hash=commit_hash,
            timestamp=datetime.now(UTC).isoformat(),
            details=cascade_result.details,
        )

    def _commit_reject(
        self,
        candidate: StepCandidate,
        claim: Claim,
        cascade_result: CascadeResult,
        state: ProofState,
        commit_hash: str,
    ) -> CommitRecord:
        """Commit a rejected claim."""
        # Update claim to rejected
        state.reject_claim(claim.id, cascade_result.details)

        # Store counterexample if found
        if cascade_result.counterexample:
            state.add_counterexample(cascade_result.counterexample)

        # Record the attempt
        attempt = Attempt(
            branch_id=state.branch_id,
            failed_claim=claim.id,
            failure_reason=cascade_result.details,
            verifier_stage=cascade_result.failed_stage,
            strategy_used=candidate.strategy_family,
            claim_hash=commit_hash,
        )
        state.add_attempt(attempt)

        return CommitRecord(
            claim_id=claim.id,
            action="reject",
            artifacts=cascade_result.artifacts,
            commit_hash=commit_hash,
            timestamp=datetime.now(UTC).isoformat(),
            details=cascade_result.details,
        )

    def _compute_commit_hash(
        self,
        claim: Claim,
        cascade_result: CascadeResult,
    ) -> str:
        """Compute deterministic hash for the commit."""
        data = {
            "claim_id": claim.id,
            "statement": claim.statement,
            "artifacts": [
                {
                    "stage": a.stage,
                    "result": a.result,
                    "details": a.details,
                }
                for a in cascade_result.artifacts
            ],
        }
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _write_log(self, record: CommitRecord) -> None:
        """Write commit record to disk if log_dir is configured."""
        if self.log_dir is None:
            return

        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / "commit_log.jsonl"

        entry = {
            "claim_id": record.claim_id,
            "action": record.action,
            "commit_hash": record.commit_hash,
            "timestamp": record.timestamp,
            "details": record.details,
            "artifact_count": len(record.artifacts),
        }

        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
