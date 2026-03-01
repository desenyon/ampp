"""
Lemma Minimization Engine (Section 10)

When Lean fails:
1. Remove redundant quantifiers
2. Introduce intermediate lemmas
3. Split casework
4. Separate implications
5. Reduce scope

Smaller lemmas are easier to verify.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MinimizationResult:
    """Result of lemma minimization."""
    original: str
    minimized_lemmas: list[str]
    strategy_used: str
    success: bool
    details: str = ""


class LemmaMinimizer:
    """
    Minimizes lemmas that fail Lean verification.

    Applies a sequence of transformations to break a complex lemma
    into simpler, more verifiable pieces.
    """

    def __init__(self, llm_assist: Any | None = None) -> None:
        self.llm_assist = llm_assist

    def minimize(
        self,
        lean_code: str,
        lean_errors: list[str] | None = None,
    ) -> MinimizationResult:
        """
        Attempt to minimize a failing Lean lemma.

        Args:
            lean_code: The Lean code that failed to compile.
            lean_errors: Error messages from Lean.

        Returns:
            MinimizationResult with simplified lemmas.
        """
        logger.info("Minimizing lemma (%d chars)", len(lean_code))

        # Try each minimization strategy in order
        strategies = [
            ("remove_sorry", self._remove_sorry_stubs),
            ("split_conjunction", self._split_conjunction),
            ("separate_implications", self._separate_implications),
            ("reduce_quantifiers", self._reduce_quantifiers),
            ("split_cases", self._split_cases),
            ("introduce_intermediate", self._introduce_intermediate),
        ]

        for name, strategy in strategies:
            result = strategy(lean_code, lean_errors)
            if result.success and len(result.minimized_lemmas) > 0:
                logger.info(
                    "Minimization succeeded with strategy '%s': "
                    "%d sub-lemmas",
                    name,
                    len(result.minimized_lemmas),
                )
                return result

        # LLM fallback
        if self.llm_assist:
            return self._llm_minimize(lean_code, lean_errors)

        return MinimizationResult(
            original=lean_code,
            minimized_lemmas=[lean_code],
            strategy_used="none",
            success=False,
            details="No minimization strategy succeeded",
        )

    def _remove_sorry_stubs(
        self, code: str, errors: list[str] | None
    ) -> MinimizationResult:
        """Remove sorry stubs and provide guided placeholders."""
        if "sorry" not in code:
            return MinimizationResult(
                original=code,
                minimized_lemmas=[],
                strategy_used="remove_sorry",
                success=False,
            )

        # Split at sorry boundaries
        parts = re.split(r"\bsorry\b", code)
        if len(parts) <= 1:
            return MinimizationResult(
                original=code,
                minimized_lemmas=[],
                strategy_used="remove_sorry",
                success=False,
            )

        # Each sorry becomes a separate lemma stub
        lemmas: list[str] = []
        for i, part in enumerate(parts[:-1]):
            lemma = part.strip()
            if lemma:
                lemmas.append(f"-- Sub-lemma {i+1}\n{lemma}\n  sorry")

        return MinimizationResult(
            original=code,
            minimized_lemmas=lemmas,
            strategy_used="remove_sorry",
            success=len(lemmas) > 1,
        )

    def _split_conjunction(
        self, code: str, errors: list[str] | None
    ) -> MinimizationResult:
        """Split P ∧ Q into separate lemmas for P and Q."""
        # Look for conjunction patterns
        conj_pattern = re.compile(
            r"(theorem|lemma)\s+(\w+).*?:\s*(.*?)\s*∧\s*(.*?)\s*:=",
            re.DOTALL,
        )
        match = conj_pattern.search(code)
        if not match:
            return MinimizationResult(
                original=code,
                minimized_lemmas=[],
                strategy_used="split_conjunction",
                success=False,
            )

        keyword = match.group(1)
        name = match.group(2)
        left = match.group(3).strip()
        right = match.group(4).strip()

        lemma1 = f"{keyword} {name}_left : {left} := by\n  sorry"
        lemma2 = f"{keyword} {name}_right : {right} := by\n  sorry"

        return MinimizationResult(
            original=code,
            minimized_lemmas=[lemma1, lemma2],
            strategy_used="split_conjunction",
            success=True,
        )

    def _separate_implications(
        self, code: str, errors: list[str] | None
    ) -> MinimizationResult:
        """Separate P → Q → R into P → Q and Q → R."""
        # Look for chained implications
        impl_pattern = re.compile(
            r"(.*?)\s*→\s*(.*?)\s*→\s*(.*)",
        )
        match = impl_pattern.search(code)
        if not match:
            return MinimizationResult(
                original=code,
                minimized_lemmas=[],
                strategy_used="separate_implications",
                success=False,
            )

        return MinimizationResult(
            original=code,
            minimized_lemmas=[],
            strategy_used="separate_implications",
            success=False,
            details="Implication separation requires type analysis",
        )

    def _reduce_quantifiers(
        self, code: str, errors: list[str] | None
    ) -> MinimizationResult:
        """Remove redundant quantifiers."""
        # Count quantifiers
        forall_count = code.count("∀")
        exists_count = code.count("∃")

        if forall_count + exists_count <= 1:
            return MinimizationResult(
                original=code,
                minimized_lemmas=[],
                strategy_used="reduce_quantifiers",
                success=False,
            )

        # Try to instantiate outer quantifier at a specific value
        # This creates a concrete sub-lemma
        reduced = re.sub(
            r"∀\s+(\w+)\s*:\s*ℕ\s*,",
            lambda m: f"-- Specialized: {m.group(1)} fixed\n",
            code,
            count=1,
        )

        if reduced != code:
            return MinimizationResult(
                original=code,
                minimized_lemmas=[reduced],
                strategy_used="reduce_quantifiers",
                success=True,
            )

        return MinimizationResult(
            original=code,
            minimized_lemmas=[],
            strategy_used="reduce_quantifiers",
            success=False,
        )

    def _split_cases(
        self, code: str, errors: list[str] | None
    ) -> MinimizationResult:
        """Split casework into separate lemmas."""
        # Look for disjunction or if-then-else patterns
        if "∨" not in code and "cases" not in code.lower():
            return MinimizationResult(
                original=code,
                minimized_lemmas=[],
                strategy_used="split_cases",
                success=False,
            )

        return MinimizationResult(
            original=code,
            minimized_lemmas=[],
            strategy_used="split_cases",
            success=False,
            details="Case splitting requires structural analysis",
        )

    def _introduce_intermediate(
        self, code: str, errors: list[str] | None
    ) -> MinimizationResult:
        """Introduce intermediate lemmas to bridge gaps."""
        if self.llm_assist is None:
            return MinimizationResult(
                original=code,
                minimized_lemmas=[],
                strategy_used="introduce_intermediate",
                success=False,
            )

        return self._llm_minimize(code, errors)

    def _llm_minimize(
        self, code: str, errors: list[str] | None
    ) -> MinimizationResult:
        """Use LLM to suggest minimized lemma decomposition."""
        import json

        error_text = "\n".join(errors or [])
        prompt = (
            "The following Lean 4 code fails to compile:\n\n"
            f"```lean\n{code}\n```\n\n"
            f"Errors:\n{error_text}\n\n"
            "Decompose this into smaller, independent lemmas that are "
            "each individually easier to prove. Return JSON:\n"
            '{"lemmas": ["lean code 1", "lean code 2", ...]}'
        )

        try:
            response = self.llm_assist(prompt)  # type: ignore[misc]
            data = json.loads(response)
            lemmas = data.get("lemmas", [])
            if lemmas:
                return MinimizationResult(
                    original=code,
                    minimized_lemmas=lemmas,
                    strategy_used="llm_minimization",
                    success=True,
                )
        except Exception as e:
            logger.warning("LLM minimization failed: %s", e)

        return MinimizationResult(
            original=code,
            minimized_lemmas=[code],
            strategy_used="llm_minimization",
            success=False,
        )
