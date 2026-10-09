"""V1: bounded integer counterexample search, never a universal proof."""

from __future__ import annotations

import random
from typing import Any

from ampp.config import cfg
from ampp.schemas import SmallCaseTest, StepCandidate
from ampp.verifiers.arithmetic import COMPARISONS, UnsupportedExpression, parse_relation
from ampp.verifiers.result import result


class CounterexampleVerifier:
    def __init__(self, seed: int | None = None) -> None:
        self._seed = cfg.random_seed if seed is None else seed
        self._rng = random.Random(self._seed)

    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        # Reset per call so preceding candidates do not change this search.
        self._rng.seed(context.get("seed", self._seed))
        for test in candidate.small_case_tests:
            witness = self._run_small_case(candidate, test)
            if witness is not None:
                return result(
                    "failed", reason=f"Small-case test failed: {test.description}", witness=witness
                )
        bound = candidate.verification_plan.enumeration_bound
        if bound is not None:
            if not 0 <= bound <= cfg.v1_max_enumeration_bound:
                return result("inconclusive", reason="Enumeration bound exceeds configured limit")
            witness = self._exhaustive_check(candidate, bound, context)
            if witness is not None:
                return result(
                    "failed", reason="Exhaustive search found counterexample", witness=witness
                )
        witness = self._random_test(candidate, context, cfg.v1_random_trials)
        if witness is not None:
            return result("failed", reason="Random search found counterexample", witness=witness)
        return result(
            "inconclusive",
            reason="No counterexample found; bounded testing is not a proof",
            random_trials=cfg.v1_random_trials,
        )

    def _run_small_case(
        self, candidate: StepCandidate, test: SmallCaseTest
    ) -> dict[str, Any] | None:
        checked = self._evaluate_claim(candidate, test.parameters)
        if checked is not None and (checked is False or checked != test.expected):
            return {"parameters": test.parameters, "got": checked, "expected": test.expected}
        return None

    def _exhaustive_check(
        self, candidate: StepCandidate, bound: int, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        for n in range(bound + 1):
            if self._evaluate_claim(candidate, {"n": n}) is False:
                return {"n": n}
        return None

    def _random_test(
        self, candidate: StepCandidate, context: dict[str, Any], trials: int
    ) -> dict[str, Any] | None:
        for _ in range(trials):
            n = self._rng.randint(-10_000, 10_000)
            if self._evaluate_claim(candidate, {"n": n}) is False:
                return {"n": n}
        return None

    def _evaluate_claim(self, candidate: StepCandidate, params: dict[str, Any]) -> bool | None:
        def symbol(name: str) -> int:
            value = params.get(name)
            if type(value) is not int or abs(value) > 10**12:
                raise UnsupportedExpression("missing or unsupported parameter")
            return value

        unknown = False
        for claim in candidate.new_claims:
            try:
                lhs, op, rhs = parse_relation(claim.statement, int, symbol)
                if not COMPARISONS[op](lhs, rhs):
                    return False
            except UnsupportedExpression:
                unknown = True
        return None if unknown else True
