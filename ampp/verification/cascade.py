"""
Verification Cascade (Section 8)

Orchestrates the escalating verification layers V0 → V5.
Each layer must pass before advancing. Failure at any layer → reject.

The cascade is the sole arbiter of truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ampp.config import PipelineConfig, VerifierConfig
from ampp.models.proof_state import ProofState
from ampp.models.state import (
    Claim,
    Counterexample,
    FormalSpec,
    VerificationArtifact,
)
from ampp.models.step_candidate import StepCandidate
from ampp.verification.v0_structural import V0StructuralChecker
from ampp.verification.v1_counterexample import V1CounterexampleSearch
from ampp.verification.v2_symbolic import V2SymbolicVerifier
from ampp.verification.v3_smt import V3SMTVerifier
from ampp.verification.v4_atp import V4ATPVerifier
from ampp.verification.v5_lean import V5LeanChecker

logger = logging.getLogger(__name__)


@dataclass
class CascadeResult:
    """Result of the full verification cascade."""
    passed: bool
    artifacts: list[VerificationArtifact] = field(default_factory=list)
    counterexample: Counterexample | None = None
    failed_stage: str = ""
    details: str = ""


class VerificationCascade:
    """
    Orchestrates the multi-layer verification cascade.

    Layers run in order V0 → V5. Each candidate's verification_plan
    specifies which layers apply. Failure at any layer stops the cascade
    and rejects the claim.

    The cascade operates on StepCandidate objects and produces
    CascadeResult objects that feed into the Two-Phase Commit.
    """

    def __init__(
        self,
        config: VerifierConfig | None = None,
    ) -> None:
        self.config = config or VerifierConfig()

        # Initialize all verifiers
        self.v0 = V0StructuralChecker()
        self.v1 = V1CounterexampleSearch(self.config)
        self.v2 = V2SymbolicVerifier(self.config)
        self.v3 = V3SMTVerifier(self.config)
        self.v4 = V4ATPVerifier(self.config)
        self.v5 = V5LeanChecker(self.config)

    def verify(
        self,
        candidate: StepCandidate,
        claim: Claim,
        spec: FormalSpec,
        state: ProofState,
        *,
        predicate: Callable[..., bool] | None = None,
        domain: dict[str, Any] | None = None,
        z3_encoding: str = "",
        tptp_problem: str = "",
    ) -> CascadeResult:
        """
        Run the verification cascade on a candidate's claim.

        Args:
            candidate: The StepCandidate being verified.
            claim: The Claim object derived from the candidate.
            spec: Formal specification.
            state: Current proof state.
            predicate: Callable for V1 counterexample search.
            domain: Variable domains for V1.
            z3_encoding: Z3 Python code for V3.
            tptp_problem: TPTP format for V4.

        Returns:
            CascadeResult with all artifacts and pass/fail.
        """
        artifacts: list[VerificationArtifact] = []
        vp = candidate.verification_plan
        applicable = set(vp.applicable_verifiers) if vp else set()

        # If no verifiers specified, use default cascade
        if not applicable:
            applicable = {"V0", "V1", "V5"}

        logger.info(
            "Cascade: verifying claim %s with layers %s",
            claim.id,
            sorted(applicable),
        )

        # ── V0: Structural Checks ─────────────────────────────────
        if "V0" in applicable or True:  # V0 always runs
            v0_result = self.v0.check(candidate, spec, state)
            artifacts.append(self.v0.to_artifact(v0_result))

            if not v0_result.passed:
                logger.info("Cascade: FAILED at V0 for %s", claim.id)
                return CascadeResult(
                    passed=False,
                    artifacts=artifacts,
                    failed_stage="V0",
                    details=v0_result.details,
                )

        # ── V1: Counterexample Search ─────────────────────────────
        if "V1" in applicable and predicate is not None:
            v1_domain = domain or {}
            v1_result = self.v1.search(
                claim.id,
                predicate,
                v1_domain,
                claim_statement=claim.statement,
            )
            artifacts.append(self.v1.to_artifact(v1_result))

            if not v1_result.passed:
                logger.info("Cascade: FAILED at V1 for %s", claim.id)
                return CascadeResult(
                    passed=False,
                    artifacts=artifacts,
                    counterexample=v1_result.counterexample,
                    failed_stage="V1",
                    details=v1_result.details,
                )

        # ── V2: Symbolic Verification ─────────────────────────────
        if "V2" in applicable:
            # Try simplifying the claim statement
            v2_result = self.v2.simplify_expression(claim.statement)
            artifacts.append(self.v2.to_artifact(v2_result))

            if not v2_result.passed:
                logger.info("Cascade: FAILED at V2 for %s", claim.id)
                return CascadeResult(
                    passed=False,
                    artifacts=artifacts,
                    failed_stage="V2",
                    details=v2_result.details,
                )

        # ── V3: SMT (Z3) ─────────────────────────────────────────
        if "V3" in applicable and z3_encoding:
            v3_result = self.v3.verify_claim(
                claim.id,
                z3_encoding,
                claim_statement=claim.statement,
            )
            artifacts.append(self.v3.to_artifact(v3_result))

            if not v3_result.passed:
                logger.info("Cascade: FAILED at V3 for %s", claim.id)
                return CascadeResult(
                    passed=False,
                    artifacts=artifacts,
                    counterexample=v3_result.counterexample,
                    failed_stage="V3",
                    details=v3_result.details,
                )

        # ── V4: ATP ───────────────────────────────────────────────
        if "V4" in applicable and tptp_problem:
            v4_result = self.v4.verify(
                claim.id,
                tptp_problem,
                claim_statement=claim.statement,
            )
            artifacts.append(self.v4.to_artifact(v4_result))

            if not v4_result.passed:
                logger.info("Cascade: FAILED at V4 for %s", claim.id)
                return CascadeResult(
                    passed=False,
                    artifacts=artifacts,
                    failed_stage="V4",
                    details=v4_result.details,
                )

        # ── V5: Lean ──────────────────────────────────────────────
        if "V5" in applicable:
            lean_code = claim.lean_code or candidate.lean_stub
            if lean_code:
                v5_result = self.v5.check(
                    claim.id,
                    lean_code,
                    claim_statement=claim.statement,
                )
                artifacts.append(self.v5.to_artifact(v5_result))

                if not v5_result.passed:
                    logger.info(
                        "Cascade: FAILED at V5 for %s", claim.id
                    )
                    return CascadeResult(
                        passed=False,
                        artifacts=artifacts,
                        failed_stage="V5",
                        details=v5_result.details,
                    )

        # ── All passed ────────────────────────────────────────────
        logger.info("Cascade: ALL PASSED for %s", claim.id)
        return CascadeResult(
            passed=True,
            artifacts=artifacts,
            details="All verification layers passed",
        )
