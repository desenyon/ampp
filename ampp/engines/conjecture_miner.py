"""
Conjecture Mining Engine (Section 13)

Continuously:
- Enumerate small instances
- Detect invariants
- Infer candidate bounds
- Suggest structural conjectures

All conjectures must still pass full verification cascade.
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from ampp.models.state import _new_id

logger = logging.getLogger(__name__)


@dataclass
class MinedConjecture:
    """A conjecture discovered by the mining engine."""
    id: str
    statement: str
    evidence: dict[str, Any]
    confidence: float  # 0.0 to 1.0 — NOT used for verification
    mining_method: str
    tested_up_to: int = 0


class ConjectureMiner:
    """
    Mines conjectures from small-instance enumeration.

    This engine generates HYPOTHESES only. All conjectures must still
    pass the full verification cascade before becoming part of the
    proof state.
    """

    def __init__(self, max_n: int = 20) -> None:
        self.max_n = max_n

    def mine_from_function(
        self,
        func: Callable[[int], Any],
        *,
        description: str = "",
    ) -> list[MinedConjecture]:
        """
        Mine conjectures by evaluating a function on small inputs.

        Detects:
        - Constant sequences
        - Monotonicity
        - Periodicity
        - Polynomial fits
        - Divisibility patterns
        - Parity patterns

        Args:
            func: Function from ℕ → value to analyze.
            description: Human-readable description.

        Returns:
            List of mined conjectures.
        """
        conjectures: list[MinedConjecture] = []

        # Evaluate function on [0, max_n]
        values: dict[int, Any] = {}
        for n in range(self.max_n + 1):
            try:
                values[n] = func(n)
            except Exception:
                break

        if len(values) < 3:
            return conjectures

        # Detect patterns
        conjectures.extend(
            self._detect_monotonicity(values, description)
        )
        conjectures.extend(
            self._detect_periodicity(values, description)
        )
        conjectures.extend(
            self._detect_bounds(values, description)
        )
        conjectures.extend(
            self._detect_divisibility(values, description)
        )
        conjectures.extend(
            self._detect_parity(values, description)
        )

        logger.info(
            "Mined %d conjectures from %s",
            len(conjectures),
            description or "function",
        )
        return conjectures

    def mine_invariant(
        self,
        transition: Callable[[Any], Any],
        measure: Callable[[Any], Any],
        initial_states: list[Any],
        steps: int = 100,
        *,
        description: str = "",
    ) -> list[MinedConjecture]:
        """
        Mine invariant conjectures by running state transitions.

        Args:
            transition: State transition function.
            measure: Function computing the measured quantity.
            initial_states: Starting states to test.
            steps: Number of transitions per state.
            description: Human-readable description.
        """
        conjectures: list[MinedConjecture] = []

        for init in initial_states:
            measures: list[Any] = []
            state = init
            try:
                for _ in range(steps):
                    measures.append(measure(state))
                    state = transition(state)
            except Exception:
                continue

            if not measures:
                continue

            # Check if measure is constant (invariant)
            if len(set(str(m) for m in measures)) == 1:
                conjectures.append(
                    MinedConjecture(
                        id=_new_id(),
                        statement=(
                            f"Invariant: measure = {measures[0]} "
                            f"under transitions ({description})"
                        ),
                        evidence={
                            "initial": str(init),
                            "value": measures[0],
                            "steps_tested": len(measures),
                        },
                        confidence=0.9,
                        mining_method="invariant_detection",
                        tested_up_to=len(measures),
                    )
                )

            # Check if measure is monotonically non-decreasing
            if all(
                measures[i] <= measures[i + 1]
                for i in range(len(measures) - 1)
                if isinstance(measures[i], (int, float))
            ):
                conjectures.append(
                    MinedConjecture(
                        id=_new_id(),
                        statement=(
                            f"Monovariant: measure is non-decreasing "
                            f"under transitions ({description})"
                        ),
                        evidence={
                            "initial": str(init),
                            "first_value": measures[0],
                            "last_value": measures[-1],
                        },
                        confidence=0.7,
                        mining_method="monovariant_detection",
                        tested_up_to=len(measures),
                    )
                )

        return conjectures

    def _detect_monotonicity(
        self, values: dict[int, Any], desc: str
    ) -> list[MinedConjecture]:
        conjectures: list[MinedConjecture] = []
        nums = [
            (k, v) for k, v in sorted(values.items())
            if isinstance(v, (int, float))
        ]
        if len(nums) < 3:
            return conjectures

        vals = [v for _, v in nums]

        if all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1)):
            conjectures.append(
                MinedConjecture(
                    id=_new_id(),
                    statement=f"f(n) is non-decreasing ({desc})",
                    evidence={"values": dict(nums)},
                    confidence=0.8,
                    mining_method="monotonicity",
                    tested_up_to=max(n for n, _ in nums),
                )
            )

        if all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)):
            conjectures.append(
                MinedConjecture(
                    id=_new_id(),
                    statement=f"f(n) is strictly increasing ({desc})",
                    evidence={"values": dict(nums)},
                    confidence=0.8,
                    mining_method="monotonicity",
                    tested_up_to=max(n for n, _ in nums),
                )
            )

        return conjectures

    def _detect_periodicity(
        self, values: dict[int, Any], desc: str
    ) -> list[MinedConjecture]:
        conjectures: list[MinedConjecture] = []
        sorted_vals = [v for _, v in sorted(values.items())]
        n = len(sorted_vals)

        for period in range(1, min(n // 2 + 1, 10)):
            periodic = True
            for i in range(period, n):
                if sorted_vals[i] != sorted_vals[i - period]:
                    periodic = False
                    break
            if periodic:
                conjectures.append(
                    MinedConjecture(
                        id=_new_id(),
                        statement=(
                            f"f(n) has period {period} ({desc})"
                        ),
                        evidence={
                            "period": period,
                            "cycle": sorted_vals[:period],
                        },
                        confidence=0.85,
                        mining_method="periodicity",
                        tested_up_to=n,
                    )
                )
                break  # Only report smallest period

        return conjectures

    def _detect_bounds(
        self, values: dict[int, Any], desc: str
    ) -> list[MinedConjecture]:
        conjectures: list[MinedConjecture] = []
        nums = [
            (k, v) for k, v in sorted(values.items())
            if isinstance(v, (int, float)) and k > 0
        ]
        if len(nums) < 5:
            return conjectures

        # Check if f(n) ≤ n^k for some small k
        for k in [1, 2, 3]:
            if all(v <= n**k for n, v in nums if n > 0):
                conjectures.append(
                    MinedConjecture(
                        id=_new_id(),
                        statement=f"f(n) ≤ n^{k} ({desc})",
                        evidence={
                            "bound_type": f"polynomial_degree_{k}",
                            "max_ratio": max(
                                v / n**k for n, v in nums if n > 0
                            ),
                        },
                        confidence=0.6,
                        mining_method="bound_detection",
                        tested_up_to=max(n for n, _ in nums),
                    )
                )
                break

        return conjectures

    def _detect_divisibility(
        self, values: dict[int, Any], desc: str
    ) -> list[MinedConjecture]:
        conjectures: list[MinedConjecture] = []
        int_vals = [
            v for v in values.values()
            if isinstance(v, int) and v != 0
        ]
        if len(int_vals) < 5:
            return conjectures

        for d in [2, 3, 4, 5, 6]:
            if all(v % d == 0 for v in int_vals):
                conjectures.append(
                    MinedConjecture(
                        id=_new_id(),
                        statement=f"{d} | f(n) for all tested n ({desc})",
                        evidence={"divisor": d},
                        confidence=0.7,
                        mining_method="divisibility",
                        tested_up_to=len(int_vals),
                    )
                )

        return conjectures

    def _detect_parity(
        self, values: dict[int, Any], desc: str
    ) -> list[MinedConjecture]:
        conjectures: list[MinedConjecture] = []
        int_vals = [
            (k, v) for k, v in values.items()
            if isinstance(v, int)
        ]
        if len(int_vals) < 5:
            return conjectures

        # Check if parity depends on input parity
        even_in_even_out = all(
            v % 2 == 0 for k, v in int_vals if k % 2 == 0
        )
        odd_in_odd_out = all(
            v % 2 == 1 for k, v in int_vals if k % 2 == 1
        )

        if even_in_even_out and odd_in_odd_out:
            conjectures.append(
                MinedConjecture(
                    id=_new_id(),
                    statement=(
                        f"f(n) preserves parity: f(even)=even, "
                        f"f(odd)=odd ({desc})"
                    ),
                    evidence={},
                    confidence=0.75,
                    mining_method="parity",
                    tested_up_to=len(int_vals),
                )
            )

        return conjectures
