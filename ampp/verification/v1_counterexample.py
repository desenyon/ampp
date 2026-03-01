"""
V1 — Counterexample Search (Section 8)

Methods:
- Exhaustive enumeration for small parameters
- Random property testing
- Boundary testing

If counterexample found:
- Claim marked rejected
- Witness stored
- Pattern extracted for refinement
"""

from __future__ import annotations

import itertools
import logging
import random
from dataclasses import dataclass
from typing import Any, Callable

from ampp.config import VerifierConfig
from ampp.models.state import Counterexample, VerificationArtifact

logger = logging.getLogger(__name__)


@dataclass
class V1Result:
    passed: bool  # True = no counterexample found
    counterexample: Counterexample | None = None
    details: str = ""
    tests_run: int = 0


class V1CounterexampleSearch:
    """
    Counterexample search engine.

    Runs exhaustive, random, and boundary tests against a predicate.
    Finding a counterexample → claim is rejected.
    Not finding one does NOT verify the claim (absence of evidence ≠ evidence).
    """

    def __init__(self, config: VerifierConfig | None = None) -> None:
        self.config = config or VerifierConfig()
        self.rng = random.Random(self.config.counterexample_seed)

    def search(
        self,
        claim_id: str,
        predicate: Callable[..., bool],
        domain: dict[str, range | list[Any]],
        *,
        claim_statement: str = "",
    ) -> V1Result:
        """
        Search for a counterexample to the given predicate.

        Args:
            claim_id: ID of the claim being tested.
            predicate: A callable that returns True if the claim holds.
            domain: Mapping from variable name to domain (range or list).
            claim_statement: Statement for logging.

        Returns:
            V1Result. passed=True means no counterexample found.
        """
        total_tests = 0

        # Phase 1: Exhaustive enumeration for small parameters
        exhaustive_result, n_tests = self._exhaustive_search(
            claim_id, predicate, domain
        )
        total_tests += n_tests
        if exhaustive_result is not None:
            return V1Result(
                passed=False,
                counterexample=exhaustive_result,
                details="Counterexample found via exhaustive search",
                tests_run=total_tests,
            )

        # Phase 2: Boundary testing
        boundary_result, n_tests = self._boundary_search(
            claim_id, predicate, domain
        )
        total_tests += n_tests
        if boundary_result is not None:
            return V1Result(
                passed=False,
                counterexample=boundary_result,
                details="Counterexample found via boundary testing",
                tests_run=total_tests,
            )

        # Phase 3: Random property testing
        random_result, n_tests = self._random_search(
            claim_id, predicate, domain
        )
        total_tests += n_tests
        if random_result is not None:
            return V1Result(
                passed=False,
                counterexample=random_result,
                details="Counterexample found via random testing",
                tests_run=total_tests,
            )

        logger.info(
            "V1: No counterexample found in %d tests for claim %s",
            total_tests,
            claim_id,
        )
        return V1Result(
            passed=True,
            details=f"No counterexample in {total_tests} tests",
            tests_run=total_tests,
        )

    def _exhaustive_search(
        self,
        claim_id: str,
        predicate: Callable[..., bool],
        domain: dict[str, range | list[Any]],
    ) -> tuple[Counterexample | None, int]:
        """Exhaustive enumeration for small parameter values."""
        # Limit domain to max_exhaustive_n
        small_domain: dict[str, list[Any]] = {}
        for var, dom in domain.items():
            if isinstance(dom, range):
                vals = [
                    v for v in dom
                    if abs(v) <= self.config.max_exhaustive_n
                ]
                small_domain[var] = vals
            else:
                small_domain[var] = list(dom)[
                    : self.config.max_exhaustive_n
                ]

        if not small_domain:
            return None, 0

        var_names = list(small_domain.keys())
        var_values = [small_domain[k] for k in var_names]
        tests = 0

        for combo in itertools.product(*var_values):
            tests += 1
            kwargs = dict(zip(var_names, combo))
            try:
                result = predicate(**kwargs)
                if not result:
                    cx = Counterexample(
                        claim_id=claim_id,
                        witness_structure=kwargs,
                        generation_method="exhaustive",
                        seed=self.config.counterexample_seed,
                    )
                    logger.info(
                        "V1 exhaustive: counterexample %s", kwargs
                    )
                    return cx, tests
            except Exception as e:
                logger.debug(
                    "V1 exhaustive: predicate error at %s: %s",
                    kwargs,
                    e,
                )

        return None, tests

    def _boundary_search(
        self,
        claim_id: str,
        predicate: Callable[..., bool],
        domain: dict[str, range | list[Any]],
    ) -> tuple[Counterexample | None, int]:
        """Test boundary values of each domain."""
        tests = 0

        for var, dom in domain.items():
            boundary_values: list[Any] = []
            if isinstance(dom, range):
                boundary_values = [
                    dom.start,
                    dom.start + 1,
                    dom.stop - 1,
                    dom.stop - 2,
                    0,
                    1,
                    -1,
                ]
            elif isinstance(dom, list) and dom:
                boundary_values = [dom[0], dom[-1]]

            for val in boundary_values:
                tests += 1
                kwargs = {var: val}
                # Fill other vars with minimal values
                for other_var, other_dom in domain.items():
                    if other_var == var:
                        continue
                    if isinstance(other_dom, range):
                        kwargs[other_var] = other_dom.start
                    elif isinstance(other_dom, list) and other_dom:
                        kwargs[other_var] = other_dom[0]

                try:
                    result = predicate(**kwargs)
                    if not result:
                        cx = Counterexample(
                            claim_id=claim_id,
                            witness_structure=kwargs,
                            generation_method="boundary",
                            seed=self.config.counterexample_seed,
                        )
                        logger.info(
                            "V1 boundary: counterexample %s", kwargs
                        )
                        return cx, tests
                except Exception:
                    pass

        return None, tests

    def _random_search(
        self,
        claim_id: str,
        predicate: Callable[..., bool],
        domain: dict[str, range | list[Any]],
    ) -> tuple[Counterexample | None, int]:
        """Random property testing."""
        tests = 0

        for _ in range(self.config.random_test_count):
            tests += 1
            kwargs: dict[str, Any] = {}

            for var, dom in domain.items():
                if isinstance(dom, range):
                    kwargs[var] = self.rng.randint(
                        dom.start, dom.stop - 1
                    )
                elif isinstance(dom, list) and dom:
                    kwargs[var] = self.rng.choice(dom)

            try:
                result = predicate(**kwargs)
                if not result:
                    cx = Counterexample(
                        claim_id=claim_id,
                        witness_structure=kwargs,
                        generation_method="random",
                        seed=self.config.counterexample_seed,
                    )
                    logger.info(
                        "V1 random: counterexample %s", kwargs
                    )
                    return cx, tests
            except Exception:
                pass

        return None, tests

    def to_artifact(self, result: V1Result) -> VerificationArtifact:
        return VerificationArtifact(
            stage="V1",
            result="pass" if result.passed else "fail",
            details=result.details,
        )
