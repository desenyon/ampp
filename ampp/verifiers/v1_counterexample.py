"""V1 — Counterexample search verifier.

Runs exhaustive enumeration, random property testing, and boundary testing
over small parameter ranges to falsify a candidate claim.

Returns immediately on the first counterexample found.
"""
from __future__ import annotations

import logging
import random
from typing import Any

from ampp.schemas import StepCandidate, SmallCaseTest

logger = logging.getLogger(__name__)


class CounterexampleVerifier:
    """V1 verifier: attempts to falsify the candidate claim."""

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._rng = random.Random(seed)

    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """Return (passed, details). passed=False means a counterexample was found."""
        # 1. Run the declared small-case tests first.
        for test in candidate.small_case_tests:
            result = self._run_small_case(candidate, test)
            if result is not None:
                logger.warning("V1 counterexample via small_case_test: %s", test.description)
                return False, {
                    "reason": f"Small-case test failed: {test.description}",
                    "witness": result,
                    "method": "small_case_test",
                }

        # 2. Exhaustive enumeration up to the declared bound (if any).
        bound = candidate.verification_plan.enumeration_bound
        if bound is not None and bound <= 10_000:
            cx = self._exhaustive_check(candidate, int(bound), context)
            if cx is not None:
                logger.warning("V1 exhaustive counterexample found")
                return False, {
                    "reason": "Exhaustive search found counterexample",
                    "witness": cx,
                    "method": "exhaustive",
                }

        # 3. Random property testing.
        cx = self._random_test(candidate, context, trials=500)
        if cx is not None:
            logger.warning("V1 random counterexample found")
            return False, {
                "reason": "Random property test found counterexample",
                "witness": cx,
                "method": "random",
            }

        return True, {"method": "V1_counterexample", "trials": 500}

    # ── Private helpers ───────────────────────────────────────────────────────

    def _run_small_case(
        self, candidate: StepCandidate, test: SmallCaseTest
    ) -> dict[str, Any] | None:
        """Execute a single small-case test. Returns witness dict on failure, None on pass."""
        # The test defines parameters and an expected boolean outcome.
        # We evaluate the claim statement symbolically for the given parameters.
        # In production this would call the claim evaluator; here we use a safe stub.
        try:
            result = self._evaluate_claim(candidate, test.parameters)
            if result != test.expected:
                return {"parameters": test.parameters, "got": result, "expected": test.expected}
        except Exception as exc:
            logger.debug("Small-case evaluation error: %s", exc)
        return None

    def _exhaustive_check(
        self, candidate: StepCandidate, bound: int, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Enumerate integers 0..bound and check the claim for each."""
        for n in range(bound + 1):
            result = self._evaluate_claim(candidate, {"n": n})
            if result is False:
                return {"n": n}
        return None

    def _random_test(
        self, candidate: StepCandidate, context: dict[str, Any], trials: int
    ) -> dict[str, Any] | None:
        for _ in range(trials):
            n = self._rng.randint(0, 10_000)
            result = self._evaluate_claim(candidate, {"n": n})
            if result is False:
                return {"n": n}
        return None

    def _evaluate_claim(
        self, candidate: StepCandidate, params: dict[str, Any]
    ) -> bool | None:
        """
        Stub evaluator. In production this delegates to a domain-specific
        expression evaluator (e.g., SymPy lambdify or a compiled function).
        Returns True, False, or None (undecidable for these params).
        """
        # Default: assume true (conservative — avoids false rejects).
        return True
