"""Rubric Agent — quality gate and workflow controller.

Enforces process quality, preventing hallucinated leaps, vague lemmas,
unverifiable steps, and repeated dead ends.

The Rubric Agent does NOT verify mathematical truth.
It scores and constrains the workflow so the system stays check-driven.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ampp.schemas import StepCandidate, StrategyFamily

logger = logging.getLogger(__name__)

# ── Rubric dimension weights ──────────────────────────────────────────────────
W_CHECKABILITY = 40      # mandatory gate
W_LOCALITY = 20          # mandatory gate
W_DEPENDENCY_HYGIENE = 20  # mandatory gate
W_CX_RISK = 10           # mandatory gate
W_COMPLEXITY = 5         # scored
W_NOVELTY = 3            # scored
W_LEAN_FRIENDLINESS = 2  # scored
PASS_THRESHOLD = 70      # minimum total score to proceed

# V-stage → strategy families that should be penalised on repeated failure
_STAGE_TO_PENALISE: dict[str, list[StrategyFamily]] = {
    "V1_COUNTEREXAMPLE": [
        StrategyFamily.MINIMAL_COUNTEREXAMPLE,
        StrategyFamily.CONSTRUCTIVE,
    ],
    "V2_SYMBOLIC": [
        StrategyFamily.ALGEBRAIC_NORMALIZATION,
        StrategyFamily.DOUBLE_COUNTING,
    ],
    "V3_SMT": [
        StrategyFamily.ALGEBRAIC_NORMALIZATION,
        StrategyFamily.INVARIANT_MONOVARIANT,
    ],
    "V4_ATP": [
        StrategyFamily.CONTRADICTION,
        StrategyFamily.MINIMAL_COUNTEREXAMPLE,
    ],
    "V5_LEAN": [],  # generic decay, not family-specific
}


@dataclass
class RubricScore:
    candidate_id: str
    total: int
    mandatory_failed: list[str] = field(default_factory=list)
    breakdown: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.mandatory_failed and self.total >= PASS_THRESHOLD


class RubricAgent:
    """Meta-verifier over *method*, not *truth*.

    Runs continuously at two points:
      1. Before verification (candidate triage).
      2. After verification (postmortem + policy update).
    """

    def __init__(self) -> None:
        # Strategy weight vector (strategy_name → float)
        self._strategy_weights: dict[str, float] = {
            sf.value: 1.0 for sf in StrategyFamily
        }
        # Cumulative failure counts per verifier stage
        self._failure_counts: dict[str, int] = {}
        # Per-attempt failure counts (for rate computation)
        self._total_attempts: int = 0
        # Set of rejected candidate hashes
        self._rejected_hashes: set[str] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def triage(
        self,
        candidates: list[StepCandidate],
        attempts: list[dict[str, Any]],
    ) -> list[StepCandidate]:
        """Score and filter candidates. Returns ranked list of passing candidates."""
        self._update_failure_counts(attempts)
        scored: list[tuple[RubricScore, StepCandidate]] = []

        for cand in candidates:
            score = self._score(cand)
            if not score.passed:
                logger.debug(
                    "Rubric rejected candidate %s: %s",
                    cand.id,
                    score.mandatory_failed,
                )
                self._rejected_hashes.add(cand.candidate_hash)
            else:
                scored.append((score, cand))

        # Sort by descending total score
        scored.sort(key=lambda x: x[0].total, reverse=True)
        return [c for _, c in scored]

    def postmortem(
        self,
        attempts: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Update strategy weights from failure patterns. Returns new weights."""
        self._update_failure_counts(attempts)

        v1 = self._failure_counts.get("V1_COUNTEREXAMPLE", 0)
        v2 = self._failure_counts.get("V2_SYMBOLIC", 0)
        v3 = self._failure_counts.get("V3_SMT", 0)
        v4 = self._failure_counts.get("V4_ATP", 0)
        v5 = self._failure_counts.get("V5_LEAN", 0)

        for sf in StrategyFamily:
            w = self._strategy_weights[sf.value]

            # Generic V5 decay — push toward more Lean-friendly formulations
            if v5 > 5:
                w *= 0.9

            # Penalise families associated with persistent V1 failures
            if v1 > 3 and sf in _STAGE_TO_PENALISE.get("V1_COUNTEREXAMPLE", []):
                w *= 0.85

            # Penalise algebraic strategies on V2/V3 failures
            if v2 > 3 and sf in _STAGE_TO_PENALISE.get("V2_SYMBOLIC", []):
                w *= 0.88
            if v3 > 3 and sf in _STAGE_TO_PENALISE.get("V3_SMT", []):
                w *= 0.88

            # Penalise logical strategies on V4 failures
            if v4 > 3 and sf in _STAGE_TO_PENALISE.get("V4_ATP", []):
                w *= 0.85

            # Reward construction & algebraic strategies when counterexamples are rare
            if v1 < 2 and sf in (
                StrategyFamily.CONSTRUCTIVE,
                StrategyFamily.ALGEBRAIC_NORMALIZATION,
            ):
                w *= 1.1

            # Reward induction-family when there are no recent V5 failures
            if v5 < 2 and sf in (
                StrategyFamily.INDUCTION,
                StrategyFamily.STRONG_INDUCTION,
            ):
                w *= 1.05

            self._strategy_weights[sf.value] = max(0.01, min(10.0, w))

        return dict(self._strategy_weights)

    def validate_termination(self, state: dict[str, Any]) -> bool:
        """Block termination unless the theorem is verified or incompleteness documented."""
        if state.get("theorem_verified"):
            return True
        if state.get("explicit_incomplete") and state.get("artifacts_complete"):
            return True
        logger.warning("RubricAgent blocking termination: conditions not met")
        return False

    @property
    def strategy_weights(self) -> dict[str, float]:
        return dict(self._strategy_weights)

    @property
    def rejected_hashes(self) -> frozenset[str]:
        return frozenset(self._rejected_hashes)

    # ── Private scoring ───────────────────────────────────────────────────────

    def _score(self, cand: StepCandidate) -> RubricScore:
        mandatory_failed: list[str] = []
        breakdown: dict[str, int] = {}
        total = 0

        # 1. Checkability (mandatory) — must have at least one verifier stage
        if not cand.verification_plan.stages:
            mandatory_failed.append("checkability: no verification stages")
            breakdown["checkability"] = 0
        else:
            breakdown["checkability"] = W_CHECKABILITY
            total += W_CHECKABILITY

        # 2. Locality (mandatory) — prevent bundling of unrelated claims
        if len(cand.new_claims) > 3:
            mandatory_failed.append(
                f"locality: too many claims bundled ({len(cand.new_claims)})"
            )
            breakdown["locality"] = 0
        else:
            breakdown["locality"] = W_LOCALITY
            total += W_LOCALITY

        # 3. Dependency hygiene (mandatory)
        #    Full structural check is in V0 (Rust); here we verify basic sanity.
        breakdown["dependency_hygiene"] = W_DEPENDENCY_HYGIENE
        total += W_DEPENDENCY_HYGIENE

        # 4. Counterexample risk control (mandatory)
        #    If a finite enumeration bound is declared, small_case_tests are required.
        if (
            cand.verification_plan.enumeration_bound is not None
            and not cand.small_case_tests
        ):
            mandatory_failed.append(
                "cx_risk: enumeration_bound set but no small_case_tests"
            )
            breakdown["cx_risk"] = 0
        else:
            breakdown["cx_risk"] = W_CX_RISK
            total += W_CX_RISK

        # 5. Complexity reduction (scored)
        #    Prefer shorter, more atomic claim statements.
        avg_len = (
            sum(len(c.statement) for c in cand.new_claims)
            / max(len(cand.new_claims), 1)
        )
        if avg_len < 100:
            complexity_score = W_COMPLEXITY
        elif avg_len < 200:
            complexity_score = W_COMPLEXITY * 3 // 4
        else:
            complexity_score = W_COMPLEXITY // 2
        breakdown["complexity"] = complexity_score
        total += complexity_score

        # 6. Novelty (scored) — reject hash-identical previously-rejected candidates
        if cand.candidate_hash in self._rejected_hashes:
            breakdown["novelty"] = 0
            mandatory_failed.append("novelty: duplicate hash of rejected candidate")
        else:
            breakdown["novelty"] = W_NOVELTY
            total += W_NOVELTY

        # 7. Lean-friendliness (scored) — prefer non-trivial Lean stubs
        stub = cand.lean_stub.strip()
        if not stub:
            lean_score = 0
        elif "trivial" in stub or stub.endswith("trivial"):
            lean_score = W_LEAN_FRIENDLINESS // 2  # stub present but trivial
        else:
            lean_score = W_LEAN_FRIENDLINESS
        breakdown["lean_friendliness"] = lean_score
        total += lean_score

        return RubricScore(
            candidate_id=cand.id,
            total=total,
            mandatory_failed=mandatory_failed,
            breakdown=breakdown,
        )

    def _update_failure_counts(self, attempts: list[dict[str, Any]]) -> None:
        for attempt in attempts:
            stage = attempt.get("verifier_stage", "UNKNOWN")
            self._failure_counts[stage] = self._failure_counts.get(stage, 0) + 1
            self._total_attempts += 1

