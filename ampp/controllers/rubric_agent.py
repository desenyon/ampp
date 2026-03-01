"""
Rubric Agent — Quality Gate and Workflow Controller (Section 15A)

The Rubric Agent enforces process quality and prevents common failure modes.
It does NOT prove math. It scores and constrains the workflow so that the
system remains check-driven.

Placed at two points:
1. Before verification (candidate triage)
2. After verification (postmortem + policy update)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ampp.config import RubricConfig, StrategyFamily
from ampp.models.proof_state import ProofState
from ampp.models.state import FormalSpec
from ampp.models.step_candidate import StepCandidate

logger = logging.getLogger(__name__)


@dataclass
class RubricScore:
    """Detailed rubric score for a StepCandidate."""
    candidate_id: str

    # Mandatory gates (pass/fail)
    checkability: bool = False
    locality: bool = False
    dependency_hygiene: bool = False
    counterexample_risk: bool = False

    # Scored dimensions (0.0 to 1.0)
    complexity_reduction: float = 0.0
    novelty: float = 0.0
    lean_friendliness: float = 0.0

    # Composite
    gate_pass: bool = False
    weighted_score: float = 0.0
    overall_pass: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class PolicyUpdate:
    """Policy update from postmortem analysis."""
    strategy_weight_deltas: dict[str, float] = field(
        default_factory=dict
    )
    new_constraints: list[str] = field(default_factory=list)
    step_size_limit: int | None = None
    required_verifiers: list[str] = field(default_factory=list)


class RubricAgent:
    """
    Quality gate and workflow controller.

    Runs at two checkpoints:
    1. Pre-verification: scores and filters StepCandidates
    2. Post-verification: updates strategy weights and policies

    Truth is NOT determined by the Rubric Agent — only by the
    deterministic verification stack. The rubric determines only
    "is this worth spending solver/Lean time on?"
    """

    def __init__(self, config: RubricConfig | None = None) -> None:
        self.config = config or RubricConfig()
        self.strategy_weights: dict[str, float] = {
            s: 1.0 for s in StrategyFamily.ALL
        }
        self.failure_patterns: dict[str, int] = {}
        self.rejected_hashes: set[str] = set()
        self.step_size_limit: int = self.config.max_step_size
        self.custom_constraints: list[str] = []

    # ─────────────────────────────────────────────────────────────
    # Pre-Verification: Score and Filter Candidates
    # ─────────────────────────────────────────────────────────────

    def score_candidate(
        self,
        candidate: StepCandidate,
        state: ProofState,
        spec: FormalSpec,
    ) -> RubricScore:
        """
        Score a StepCandidate against the rubric.

        Returns a RubricScore with gate pass/fail and weighted score.
        """
        score = RubricScore(candidate_id=candidate.id)

        # ── Mandatory Gates ───────────────────────────────────────

        # 1. Checkability
        score.checkability = self._check_checkability(candidate)
        if not score.checkability:
            score.notes.append("GATE FAIL: Missing verification plan")

        # 2. Locality
        score.locality = self._check_locality(candidate)
        if not score.locality:
            score.notes.append("GATE FAIL: Step too large or non-local")

        # 3. Dependency Hygiene
        score.dependency_hygiene = self._check_dependency_hygiene(
            candidate, state
        )
        if not score.dependency_hygiene:
            score.notes.append("GATE FAIL: Unverified dependencies")

        # 4. Counterexample Risk
        score.counterexample_risk = self._check_counterexample_risk(
            candidate
        )
        if not score.counterexample_risk:
            score.notes.append(
                "GATE FAIL: No small_case_tests for falsifiable domain"
            )

        # All gates must pass
        score.gate_pass = (
            score.checkability
            and score.locality
            and score.dependency_hygiene
            and score.counterexample_risk
        )

        # ── Scored Dimensions ─────────────────────────────────────

        # 5. Complexity Reduction
        score.complexity_reduction = (
            self._score_complexity_reduction(candidate)
        )

        # 6. Novelty / Non-repetition
        score.novelty = self._score_novelty(candidate, state)

        # 7. Lean-Friendliness
        score.lean_friendliness = self._score_lean_friendliness(
            candidate
        )

        # ── Composite Score ───────────────────────────────────────
        cfg = self.config
        score.weighted_score = (
            score.complexity_reduction * cfg.weight_complexity_reduction
            + score.novelty * cfg.weight_novelty
            + score.lean_friendliness * cfg.weight_lean_friendliness
        ) / (
            cfg.weight_complexity_reduction
            + cfg.weight_novelty
            + cfg.weight_lean_friendliness
        )

        score.overall_pass = (
            score.gate_pass
            and score.weighted_score >= self.config.pass_threshold
        )

        return score

    def filter_candidates(
        self,
        candidates: list[StepCandidate],
        state: ProofState,
        spec: FormalSpec,
    ) -> list[StepCandidate]:
        """
        Filter and rank candidates through the rubric.

        Returns only candidates that pass all gates and meet the
        score threshold, ordered by score (best first).
        """
        scored: list[tuple[StepCandidate, RubricScore]] = []

        for candidate in candidates:
            rubric_score = self.score_candidate(
                candidate, state, spec
            )

            if rubric_score.overall_pass:
                updated = candidate.with_rubric(
                    score=rubric_score.weighted_score,
                    passed=True,
                    notes="; ".join(rubric_score.notes),
                )
                scored.append((updated, rubric_score))
            else:
                logger.debug(
                    "Rubric: rejected %s — %s",
                    candidate.id,
                    "; ".join(rubric_score.notes),
                )

        # Sort by weighted score (descending)
        scored.sort(key=lambda x: -x[1].weighted_score)

        result = [c for c, _ in scored]
        logger.info(
            "Rubric: %d/%d candidates passed",
            len(result),
            len(candidates),
        )
        return result

    # ─────────────────────────────────────────────────────────────
    # Post-Verification: Postmortem and Policy Update
    # ─────────────────────────────────────────────────────────────

    def postmortem(
        self,
        candidate: StepCandidate,
        verified: bool,
        failed_stage: str = "",
        state: ProofState | None = None,
    ) -> PolicyUpdate:
        """
        Analyze verification outcome and update policies.

        Called after every verification attempt (pass or fail).
        """
        update = PolicyUpdate()

        strategy = candidate.strategy_family

        if verified:
            # Success: increase strategy weight
            if strategy in self.strategy_weights:
                delta = 0.3
                self.strategy_weights[strategy] = min(
                    self.strategy_weights[strategy] + delta, 5.0
                )
                update.strategy_weight_deltas[strategy] = delta

            logger.info(
                "Rubric postmortem: verified (%s) → weight +%.1f",
                strategy,
                0.3,
            )
        else:
            # Failure: decrease strategy weight, track pattern
            if strategy in self.strategy_weights:
                delta = -0.15
                self.strategy_weights[strategy] = max(
                    self.strategy_weights[strategy] + delta, 0.1
                )
                update.strategy_weight_deltas[strategy] = delta

            # Track failure stage
            if failed_stage:
                self.failure_patterns[failed_stage] = (
                    self.failure_patterns.get(failed_stage, 0) + 1
                )

            # Hash the failed candidate to prevent repetition
            claim_hash = self._hash_claims(candidate.new_claims)
            self.rejected_hashes.add(claim_hash)

            # Adapt constraints based on failure patterns
            update = self._adapt_constraints(update)

            logger.info(
                "Rubric postmortem: rejected at %s (%s) → weight %.1f",
                failed_stage,
                strategy,
                delta,
            )

        return update

    def validate_termination(self, state: ProofState) -> bool:
        """
        Validate whether the proof can terminate.

        Blocks termination unless:
        - Top-level theorem is verified (Lean compiles), OR
        - State explicitly marks incompleteness with all artifacts
        """
        if state.has_verified_theorem():
            logger.info(
                "Rubric: termination APPROVED — theorem verified"
            )
            return True

        logger.info(
            "Rubric: termination BLOCKED — no verified theorem"
        )
        return False

    # ─────────────────────────────────────────────────────────────
    # Private: Gate Checks
    # ─────────────────────────────────────────────────────────────

    def _check_checkability(self, candidate: StepCandidate) -> bool:
        """Gate 1: Candidate has a concrete, executable verification plan."""
        vp = candidate.verification_plan
        if vp is None:
            return False
        if not vp.applicable_verifiers:
            return False
        if not vp.success_criteria:
            return False
        return True

    def _check_locality(self, candidate: StepCandidate) -> bool:
        """Gate 2: Step is a micro-lemma, not a macro-leap."""
        # Check number of new claims
        if len(candidate.new_claims) > self.step_size_limit:
            return False
        # Check that action_type is valid
        valid_actions = {
            "introduce_definition",
            "propose_lemma",
            "apply_lemma",
            "case_split",
            "induction_step",
            "rewrite",
            "construct_witness",
            "bound_argument",
        }
        if candidate.action_type not in valid_actions:
            return False
        return True

    def _check_dependency_hygiene(
        self, candidate: StepCandidate, state: ProofState
    ) -> bool:
        """Gate 3: Dependencies are all verified."""
        verified_ids = state.verified_claim_ids
        for dep in candidate.dependencies:
            if dep not in verified_ids:
                # Check if it's a definition (allowed)
                if dep not in state.definitions:
                    return False
        return True

    def _check_counterexample_risk(
        self, candidate: StepCandidate
    ) -> bool:
        """Gate 4: Has small-case tests if domain admits falsification."""
        if not self.config.require_small_case_tests:
            return True
        # If verification plan mentions V1, tests are required
        vp = candidate.verification_plan
        if vp and "V1" in vp.applicable_verifiers:
            if not candidate.small_case_tests:
                return False
        return True

    # ─────────────────────────────────────────────────────────────
    # Private: Scored Dimensions
    # ─────────────────────────────────────────────────────────────

    def _score_complexity_reduction(
        self, candidate: StepCandidate
    ) -> float:
        """Score 5: Does the step reduce complexity?"""
        score = 0.5  # Default neutral

        if candidate.complexity_reduction_estimate > 0:
            score = min(
                0.5 + candidate.complexity_reduction_estimate * 0.1,
                1.0,
            )

        # Bonus for case splits (reduce search space)
        if candidate.action_type == "case_split":
            score = min(score + 0.2, 1.0)

        # Bonus for rewrites (simplify)
        if candidate.action_type == "rewrite":
            score = min(score + 0.15, 1.0)

        return score

    def _score_novelty(
        self, candidate: StepCandidate, state: ProofState
    ) -> float:
        """Score 6: Is this step novel (not previously attempted)?"""
        claim_hash = self._hash_claims(candidate.new_claims)

        if claim_hash in self.rejected_hashes:
            return 0.0

        if claim_hash in state.claim_hashes():
            return 0.1

        return 1.0

    def _score_lean_friendliness(
        self, candidate: StepCandidate
    ) -> float:
        """Score 7: Is this likely to compile in Lean?"""
        score = 0.5

        lean_stub = candidate.lean_stub
        if not lean_stub:
            return 0.0

        # Positive signals
        if "theorem" in lean_stub or "lemma" in lean_stub:
            score += 0.2
        if "by" in lean_stub:
            score += 0.1
        if "sorry" in lean_stub:
            score -= 0.1  # Has sorry but at least has structure

        # Negative signals
        if len(lean_stub) > 2000:
            score -= 0.2  # Too complex
        if lean_stub.count("sorry") > 3:
            score -= 0.2  # Too many gaps

        return max(0.0, min(score, 1.0))

    # ─────────────────────────────────────────────────────────────
    # Private: Helpers
    # ─────────────────────────────────────────────────────────────

    def _hash_claims(self, claims: tuple[str, ...]) -> str:
        """Compute hash of claim statements for deduplication."""
        data = json.dumps(sorted(claims), sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def _adapt_constraints(
        self, update: PolicyUpdate
    ) -> PolicyUpdate:
        """Adapt policies based on accumulated failure patterns."""
        # A. If many V1 failures: tighten falsification bounds
        v1_failures = self.failure_patterns.get("V1", 0)
        if v1_failures >= 3:
            update.new_constraints.append(
                "Require exhaustive testing up to n=15 before V3/V5"
            )

        # B. If many V3 failures: enforce SMT-friendly restatements
        v3_failures = self.failure_patterns.get("V3", 0)
        if v3_failures >= 3:
            update.new_constraints.append(
                "Require z3_encoding_hint in verification plan"
            )
            update.required_verifiers.append("V3")

        # C. If many V5 failures: enforce smaller steps
        v5_failures = self.failure_patterns.get("V5", 0)
        if v5_failures >= 3:
            self.step_size_limit = max(
                self.step_size_limit - 1, 1
            )
            update.step_size_limit = self.step_size_limit
            update.new_constraints.append(
                f"Step size reduced to {self.step_size_limit}"
            )

        return update

    def get_strategy_weights(self) -> dict[str, float]:
        """Return current strategy weights for the ensemble."""
        return dict(self.strategy_weights)
