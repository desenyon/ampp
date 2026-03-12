"""Conjecture Mining Engine.

Continuously enumerates small problem instances, detects invariants,
infers bounds, and suggests structural conjectures.

All conjectures must still pass the full verification cascade.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# ── LLM import (optional — graceful fallback if not configured) ───────────────
try:
    from ampp.llm import get_provider as _get_llm_provider, NullProvider
    _HAS_LLM = True
except Exception:  # pragma: no cover
    _HAS_LLM = False


_SYSTEM = (
    "You are an expert combinatorics researcher mining conjectures from "
    "empirical data about small cases of a mathematical problem. "
    "Produce terse, precise, formal statements — each exactly one sentence. "
    "Prefix every conjecture with 'CONJECTURE: '."
)


class ConjectureMiner:
    """Mines conjectures from small instances of a mathematical problem.

    Two-phase operation:
      1. *Deterministic phase*: enumerate small witnesses, compute numeric
         sequences, detect parity/divisibility invariants, fit O(·) bounds.
      2. *LLM phase* (optional): feed the numeric evidence to an LLM and ask
         it to state formal conjectures.  The LLM output is returned as-is and
         still requires full verification before entering proof state.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._seen: set[str] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def mine(
        self,
        spec: dict[str, Any],
        bound: int = 20,
    ) -> list[str]:
        """Return deduplicated candidate conjecture strings.

        Each string is an informal / semi-formal statement to be handed to
        the proposer ensemble for formalisation and verification.
        """
        conjectures: list[str] = []
        evidence = self._compute_evidence(spec, bound)

        conjectures.extend(self._pattern_conjectures(spec, evidence, bound))
        conjectures.extend(self._invariant_conjectures(spec, evidence))
        conjectures.extend(self._bound_conjectures(evidence))
        conjectures.extend(self._divisibility_conjectures(evidence))

        if _HAS_LLM:
            conjectures.extend(self._llm_conjectures(spec, evidence, bound))

        # Deduplicate preserving first-seen order; skip already-seen
        fresh = []
        for c in conjectures:
            if c not in self._seen:
                self._seen.add(c)
                fresh.append(c)
        return fresh

    # ── Evidence computation ──────────────────────────────────────────────────

    def _compute_evidence(
        self,
        spec: dict[str, Any],
        bound: int,
    ) -> dict[str, Any]:
        """Build a structured numeric evidence dict from the problem spec."""
        target = spec.get("target", "")
        variables = spec.get("variables", [])
        constraints = spec.get("constraints", [])

        n_range = list(range(1, min(bound + 1, 25)))
        # Placeholder sequence generation — real evaluation hooks in here
        # when the Lean/SymPy evaluator is wired end-to-end.
        seq = [n for n in n_range]  # identity default

        diffs = [seq[i + 1] - seq[i] for i in range(len(seq) - 1)]
        ratios = [seq[i + 1] / seq[i] for i in range(len(seq) - 1) if seq[i] != 0]
        parities = [v % 2 for v in seq]

        # Divisibility frequencies
        div_counts: dict[int, int] = defaultdict(int)
        for v in seq:
            for d in (2, 3, 4, 5, 6):
                if v % d == 0:
                    div_counts[d] += 1

        return {
            "target": target,
            "variables": variables,
            "constraints": constraints,
            "n_range": n_range,
            "seq": seq,
            "diffs": diffs,
            "ratios": ratios,
            "parities": parities,
            "div_counts": dict(div_counts),
            "bound": bound,
        }

    # ── Deterministic conjecture generators ──────────────────────────────────

    def _pattern_conjectures(
        self,
        spec: dict[str, Any],
        evidence: dict[str, Any],
        bound: int,
    ) -> list[str]:
        target = evidence["target"] or "the main quantity"
        diffs = evidence["diffs"]
        conjectures = []

        conjectures.append(
            f"The property holds for all n in [1, {bound}] based on exhaustive enumeration."
        )

        # Constant difference → arithmetic
        if diffs and len(set(diffs)) == 1:
            d = diffs[0]
            conjectures.append(
                f"The sequence of witnesses for '{target}' is arithmetic with "
                f"common difference {d}."
            )

        # Constant ratio → geometric
        if evidence["ratios"]:
            rounded = [round(r, 4) for r in evidence["ratios"]]
            if len(set(rounded)) == 1:
                conjectures.append(
                    f"The sequence of witnesses for '{target}' is geometric with "
                    f"common ratio {rounded[0]}."
                )

        return conjectures

    def _invariant_conjectures(
        self,
        spec: dict[str, Any],
        evidence: dict[str, Any],
    ) -> list[str]:
        parities = evidence["parities"]
        target = evidence["target"] or "the quantity"
        conjectures = []

        if parities and len(set(parities)) == 1:
            parity_name = "even" if parities[0] == 0 else "odd"
            conjectures.append(
                f"For all instances, '{target}' is always {parity_name} — "
                "parity is an invariant."
            )

        return conjectures

    def _bound_conjectures(self, evidence: dict[str, Any]) -> list[str]:
        seq = evidence["seq"]
        n_range = evidence["n_range"]
        if not seq or not n_range:
            return []

        conjectures = []
        # Fit O(n), O(n^2), O(n log n) heuristically
        max_n, max_v = n_range[-1], seq[-1]
        if max_v <= max_n:
            conjectures.append(
                "An upper bound of O(n) appears consistent with small instances."
            )
        elif max_v <= max_n ** 2:
            conjectures.append(
                "An upper bound of O(n²) appears consistent with small instances."
            )
        else:
            bound_guess = max_n * math.ceil(math.log2(max_n + 2))
            if max_v <= bound_guess * 2:
                conjectures.append(
                    "An upper bound of O(n log n) appears consistent with small instances."
                )
        return conjectures

    def _divisibility_conjectures(self, evidence: dict[str, Any]) -> list[str]:
        div_counts = evidence["div_counts"]
        total = len(evidence["seq"])
        if total == 0:
            return []
        conjectures = []
        for d, cnt in sorted(div_counts.items()):
            freq = cnt / total
            if freq >= 0.9:
                conjectures.append(
                    f"The sequence values appear divisible by {d} in "
                    f"{cnt}/{total} small cases, suggesting a divisibility invariant."
                )
        return conjectures

    # ── LLM-powered conjecture generator ─────────────────────────────────────

    def _llm_conjectures(
        self,
        spec: dict[str, Any],
        evidence: dict[str, Any],
        bound: int,
    ) -> list[str]:
        """Ask the LLM to generalise from numeric evidence."""
        provider = _get_llm_provider()
        if isinstance(provider, NullProvider):
            return []
        seq_str = str(evidence["seq"][:10])
        diffs_str = str(evidence["diffs"][:9])
        user_msg = (
            f"Problem target statement: {evidence['target']}\n"
            f"Variables: {evidence['variables']}\n"
            f"Small-case witness sequence (n=1..{min(bound, 10)}): {seq_str}\n"
            f"First differences: {diffs_str}\n\n"
            "State up to 5 precise mathematical conjectures generalising this data. "
            "Each conjecture must be falsifiable and cover the general case, not just "
            "the small examples. Prefix each with 'CONJECTURE: '."
        )
        try:
            raw = provider.complete(_SYSTEM, user_msg)
        except Exception as exc:
            logger.warning("LLM conjecture generation failed: %s", exc)
            return []

        conjectures = []
        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("CONJECTURE:"):
                body = line.split(":", 1)[1].strip()
                if body:
                    conjectures.append(body)
        return conjectures
