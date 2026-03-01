"""
Strategy Switching Controller (Section 14)

Triggered when:
- No verified claims for M iterations
- Repeated identical failure reasons
- Frontier entropy exceeds threshold

Switches among proof strategies to prevent dead ends.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass

from ampp.config import StrategyConfig, StrategyFamily
from ampp.models.proof_state import ProofState

logger = logging.getLogger(__name__)


@dataclass
class StrategyDecision:
    """Decision from the strategy controller."""
    should_switch: bool
    current_strategy: str
    recommended_strategy: str
    reason: str
    weights: dict[str, float]


class StrategyController:
    """
    Controls strategy selection and switching.

    Maintains a weight vector over strategy families and triggers
    switches when progress stalls.
    """

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()
        self.weights: dict[str, float] = dict(
            self.config.initial_weights
        )
        self.current_strategy: str = StrategyFamily.INDUCTION
        self.iterations_without_progress: int = 0
        self.last_verified_count: int = 0
        self.failure_log: list[str] = []

    def evaluate(
        self,
        state: ProofState,
        *,
        last_strategy: str = "",
    ) -> StrategyDecision:
        """
        Evaluate whether a strategy switch is needed.

        Args:
            state: Current proof state.
            last_strategy: Strategy used in the last iteration.

        Returns:
            StrategyDecision with recommendation.
        """
        verified_count = len(state.verified_claims)

        # Check progress
        if verified_count > self.last_verified_count:
            self.iterations_without_progress = 0
            self.last_verified_count = verified_count
        else:
            self.iterations_without_progress += 1

        # Check conditions for switch
        should_switch = False
        reason = ""

        # Condition 1: Stall
        if (
            self.iterations_without_progress
            >= self.config.stall_threshold
        ):
            should_switch = True
            reason = (
                f"No progress for {self.iterations_without_progress} "
                f"iterations (threshold={self.config.stall_threshold})"
            )

        # Condition 2: Repeated failures
        failure_modes = state.failure_modes()
        if failure_modes:
            most_common_stage = max(
                failure_modes, key=lambda k: failure_modes[k]
            )
            if failure_modes[most_common_stage] >= 3:
                should_switch = True
                reason = (
                    f"Repeated failures at {most_common_stage} "
                    f"({failure_modes[most_common_stage]} times)"
                )

        # Condition 3: Entropy
        entropy = self._compute_frontier_entropy(state)
        if entropy > self.config.entropy_threshold:
            should_switch = True
            reason = f"Frontier entropy too high: {entropy:.3f}"

        # Determine recommendation
        if should_switch:
            recommended = self._select_next_strategy(
                state, last_strategy
            )
            self.iterations_without_progress = 0
        else:
            recommended = last_strategy or self.current_strategy

        decision = StrategyDecision(
            should_switch=should_switch,
            current_strategy=last_strategy or self.current_strategy,
            recommended_strategy=recommended,
            reason=reason,
            weights=dict(self.weights),
        )

        if should_switch:
            self.current_strategy = recommended
            logger.info(
                "Strategy switch: %s → %s (%s)",
                last_strategy,
                recommended,
                reason,
            )

        return decision

    def update_weights(
        self,
        strategy: str,
        *,
        success: bool,
        magnitude: float = 1.0,
    ) -> None:
        """
        Update strategy weight based on outcome.

        Success increases weight, failure decreases it.
        """
        if strategy not in self.weights:
            return

        if success:
            self.weights[strategy] = min(
                self.weights[strategy] + 0.2 * magnitude, 5.0
            )
        else:
            self.weights[strategy] = max(
                self.weights[strategy] - 0.1 * magnitude, 0.1
            )

        logger.debug(
            "Weight update: %s → %.2f (%s)",
            strategy,
            self.weights[strategy],
            "success" if success else "failure",
        )

    def _select_next_strategy(
        self,
        state: ProofState,
        exclude: str = "",
    ) -> str:
        """Select the best strategy to try next."""
        # Sort by weight, exclude current if possible
        candidates = [
            (strategy, weight)
            for strategy, weight in self.weights.items()
            if strategy != exclude and weight > 0
        ]

        if not candidates:
            # Fall back to all strategies
            candidates = list(self.weights.items())

        candidates.sort(key=lambda x: -x[1])

        # Adapt based on failure patterns
        failure_modes = state.failure_modes()

        # If many V1 failures → prefer algebraic/invariant approaches
        if failure_modes.get("V1", 0) >= 3:
            for strategy in [
                StrategyFamily.ALGEBRAIC,
                StrategyFamily.INVARIANT,
            ]:
                if strategy in dict(candidates):
                    return strategy

        # If many V3 failures → prefer constructive
        if failure_modes.get("V3", 0) >= 3:
            if StrategyFamily.CONSTRUCTION in dict(candidates):
                return StrategyFamily.CONSTRUCTION

        # If many V5 failures → prefer counting/extremal (simpler Lean)
        if failure_modes.get("V5", 0) >= 3:
            for strategy in [
                StrategyFamily.COUNTING,
                StrategyFamily.EXTREMAL,
            ]:
                if strategy in dict(candidates):
                    return strategy

        return candidates[0][0] if candidates else StrategyFamily.INDUCTION

    def _compute_frontier_entropy(
        self, state: ProofState
    ) -> float:
        """Compute entropy of open subgoal strategies."""
        strategies = [
            sg.expected_strategy
            for sg in state.open_subgoals
            if sg.expected_strategy
        ]

        if not strategies:
            return 0.0

        counter = Counter(strategies)
        total = len(strategies)

        entropy = 0.0
        for count in counter.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        # Normalize by log2(number of categories)
        max_entropy = math.log2(max(len(counter), 1))
        if max_entropy > 0:
            entropy /= max_entropy

        return entropy

    def get_ranked_strategies(self) -> list[tuple[str, float]]:
        """Return strategies ranked by weight (highest first)."""
        return sorted(
            self.weights.items(), key=lambda x: -x[1]
        )
