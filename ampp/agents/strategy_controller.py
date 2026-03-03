"""Strategy Switching Controller.

Triggered when:
  • No verified claims for M consecutive iterations
  • Repeated identical failure reasons
  • Frontier entropy exceeds threshold

Selects the next strategy from the weighted family list.
"""
from __future__ import annotations

import logging
import random
from collections import Counter
from typing import Any

from ampp.schemas import StrategyFamily

logger = logging.getLogger(__name__)

ALL_STRATEGIES = list(StrategyFamily)
SWITCH_STALE_THRESHOLD = 5
MAX_IDENTICAL_FAILURES = 3


class StrategyController:
    """Decides when and how to switch proof strategies."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._iteration_without_progress = 0
        self._last_failure_reason: str | None = None
        self._identical_failure_count = 0
        self._current_strategy = StrategyFamily.INDUCTION

    def record_progress(self) -> None:
        self._iteration_without_progress = 0
        self._last_failure_reason = None
        self._identical_failure_count = 0

    def record_failure(self, reason: str) -> None:
        self._iteration_without_progress += 1
        if reason == self._last_failure_reason:
            self._identical_failure_count += 1
        else:
            self._last_failure_reason = reason
            self._identical_failure_count = 1

    def should_switch(self) -> bool:
        if self._iteration_without_progress >= SWITCH_STALE_THRESHOLD:
            return True
        if self._identical_failure_count >= MAX_IDENTICAL_FAILURES:
            return True
        return False

    def next_strategy(
        self,
        weights: dict[str, float],
        current_strategies: list[str],
    ) -> StrategyFamily:
        """Pick the highest-weighted strategy not currently in use."""
        available = [
            sf for sf in ALL_STRATEGIES
            if sf.value not in current_strategies
        ]
        if not available:
            available = ALL_STRATEGIES  # can repeat if exhausted

        # Weighted sampling
        names = [sf.value for sf in available]
        w = [max(weights.get(n, 1.0), 0.01) for n in names]
        chosen = self._rng.choices(available, weights=w, k=1)[0]
        self._current_strategy = chosen
        self._iteration_without_progress = 0
        logger.info("Strategy switch → %s", chosen.value)
        return chosen

    def frontier_entropy(self, attempts: list[dict[str, Any]]) -> float:
        """Shannon entropy over failure stages (high = diverse failures = switch)."""
        stages = [a.get("verifier_stage", "UNKNOWN") for a in attempts[-50:]]
        if not stages:
            return 0.0
        counts = Counter(stages)
        total = len(stages)
        import math
        return -sum((c / total) * math.log2(c / total) for c in counts.values())
