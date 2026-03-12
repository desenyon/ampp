"""Strategy Switching Controller.

Triggered when:
  • No verified claims for M consecutive iterations
  • Repeated identical failure reasons
  • Frontier entropy exceeds threshold
  • Beam states collapse into near-duplicate strategies

Selects the next strategy from the weighted family list, enforcing
beam-state diversity across concurrent proof branches.
"""
from __future__ import annotations

import logging
import math
import random
from collections import Counter
from typing import Any

from ampp.schemas import StrategyFamily

logger = logging.getLogger(__name__)

ALL_STRATEGIES = list(StrategyFamily)
SWITCH_STALE_THRESHOLD = 5      # iterations without progress → force switch
MAX_IDENTICAL_FAILURES = 3      # same failure reason → force switch
ENTROPY_SWITCH_THRESHOLD = 2.5  # Shannon entropy over recent failures → switch
# Minimum fraction of beam slots that must use distinct strategy families
BEAM_DIVERSITY_RATIO = 0.6


class StrategyController:
    """Decides when and how to switch proof strategies.

    Responsibilities:
      - Track stale iterations and failure repetition.
      - Compute frontier entropy from recent attempt logs.
      - Select the next strategy via weighted sampling, enforcing diversity.
      - Provide beam governance: reject near-duplicate strategy assignments.
    """

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._iteration_without_progress: int = 0
        self._last_failure_reason: str | None = None
        self._identical_failure_count: int = 0
        self._current_strategy = StrategyFamily.INDUCTION
        # History of strategies chosen (for diversity tracking)
        self._recent_strategies: list[str] = []

    # ── State update ──────────────────────────────────────────────────────────

    def record_progress(self) -> None:
        """Call whenever a verified claim is added to state."""
        self._iteration_without_progress = 0
        self._last_failure_reason = None
        self._identical_failure_count = 0

    def record_failure(self, reason: str) -> None:
        """Call after each failed verification attempt."""
        self._iteration_without_progress += 1
        if reason == self._last_failure_reason:
            self._identical_failure_count += 1
        else:
            self._last_failure_reason = reason
            self._identical_failure_count = 1

    # ── Decision API ─────────────────────────────────────────────────────────

    def should_switch(self, attempts: list[dict[str, Any]] | None = None) -> bool:
        """Return True when the controller recommends a strategy switch."""
        if self._iteration_without_progress >= SWITCH_STALE_THRESHOLD:
            logger.debug("Switch: stale for %d iterations", self._iteration_without_progress)
            return True
        if self._identical_failure_count >= MAX_IDENTICAL_FAILURES:
            logger.debug("Switch: identical failure ×%d", self._identical_failure_count)
            return True
        if attempts is not None:
            h = self.frontier_entropy(attempts)
            if h > ENTROPY_SWITCH_THRESHOLD:
                logger.debug("Switch: frontier entropy %.2f > threshold", h)
                return True
        return False

    def next_strategy(
        self,
        weights: dict[str, float],
        current_strategies: list[str],
    ) -> StrategyFamily:
        """Pick the next strategy via weighted sampling with diversity enforcement.

        1. Exclude strategies already used in ``current_strategies`` (beam diversity).
        2. If all strategies are in use, exclude only the *current* strategy.
        3. Apply weight vector for sampling.
        4. Reset stale counter.
        """
        in_use = set(current_strategies)
        available = [sf for sf in ALL_STRATEGIES if sf.value not in in_use]
        if not available:
            # All strategies exhausted — allow all except current
            available = [sf for sf in ALL_STRATEGIES if sf != self._current_strategy]
        if not available:
            available = ALL_STRATEGIES

        names = [sf.value for sf in available]
        w = [max(weights.get(n, 1.0), 0.01) for n in names]
        chosen = self._rng.choices(available, weights=w, k=1)[0]

        self._current_strategy = chosen
        self._iteration_without_progress = 0
        self._recent_strategies.append(chosen.value)
        if len(self._recent_strategies) > 20:
            self._recent_strategies = self._recent_strategies[-20:]

        logger.info("Strategy switch → %s", chosen.value)
        return chosen

    def enforce_beam_diversity(
        self,
        beam_strategies: list[str],
        weights: dict[str, float],
    ) -> list[str]:
        """Ensure at least BEAM_DIVERSITY_RATIO of beam slots use distinct families.

        Takes the current list of per-beam-slot strategy names and returns a
        (possibly updated) list where near-duplicates are replaced.
        """
        n = len(beam_strategies)
        if n < 2:
            return beam_strategies

        required_unique = max(1, math.ceil(n * BEAM_DIVERSITY_RATIO))
        counts = Counter(beam_strategies)
        unique_now = len(counts)

        if unique_now >= required_unique:
            return beam_strategies

        result = list(beam_strategies)
        all_vals = {sf.value for sf in ALL_STRATEGIES}
        missing = list(all_vals - set(beam_strategies))

        # Replace excess duplicates with missing strategies
        for i, s in enumerate(result):
            if counts[s] > 1 and missing:
                replacement = missing.pop(0)
                counts[s] -= 1
                result[i] = replacement
                if len(Counter(result)) >= required_unique:
                    break

        return result

    # ── Analytics ─────────────────────────────────────────────────────────────

    def frontier_entropy(self, attempts: list[dict[str, Any]]) -> float:
        """Shannon entropy over failure stages in the most recent 50 attempts.

        High entropy means diverse failures → the frontier is broad and
        switching strategy may not help; the system should keep exploring.
        Low entropy (one dominant failure) → switch strategy.
        """
        stages = [a.get("verifier_stage", "UNKNOWN") for a in attempts[-50:]]
        if not stages:
            return 0.0
        counts = Counter(stages)
        total = len(stages)
        return -sum(
            (c / total) * math.log2(c / total) for c in counts.values()
        )

    @property
    def current_strategy(self) -> StrategyFamily:
        return self._current_strategy

    @property
    def stale_iterations(self) -> int:
        return self._iteration_without_progress
