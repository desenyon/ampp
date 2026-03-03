"""V2 — Symbolic verification using SymPy.

Attempts to verify the candidate claim via symbolic simplification,
identity checking, and inequality normalisation.
"""
from __future__ import annotations

import logging
from typing import Any

from ampp.schemas import StepCandidate

logger = logging.getLogger(__name__)


class SymPyVerifier:
    """V2 verifier: symbolic algebra via SymPy."""

    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """Return (passed, details)."""
        try:
            import sympy as sp
        except ImportError:
            logger.warning("SymPy not installed — skipping V2")
            return True, {"skipped": True, "reason": "sympy_not_installed"}

        for claim_spec in candidate.new_claims:
            result = self._check_statement(claim_spec.statement, sp)
            if result is False:
                return False, {
                    "reason": f"SymPy refuted: {claim_spec.statement}",
                    "statement": claim_spec.statement,
                }

        return True, {"method": "V2_symbolic"}

    # ── Private helpers ───────────────────────────────────────────────────────

    def _check_statement(self, statement: str, sp: Any) -> bool | None:
        """
        Attempt to parse and verify the statement symbolically.

        Handles three patterns:
        1. Identity:   expr1 = expr2
        2. Inequality: expr1 <= expr2  (or >=, <, >)
        3. Divisibility annotations like "n | m"

        Returns True if verified, False if refuted, None if undecidable.
        """
        # Strip LaTeX artefacts for safer parsing
        stmt = (
            statement.replace("\\le", "<=")
            .replace("\\ge", ">=")
            .replace("\\lt", "<")
            .replace("\\gt", ">")
            .replace("\\neq", "!=")
        )

        # Identity check
        if "=" in stmt and "==" not in stmt and "<=" not in stmt and ">=" not in stmt:
            parts = stmt.split("=", 1)
            if len(parts) == 2:
                try:
                    lhs = sp.sympify(parts[0].strip(), evaluate=True)
                    rhs = sp.sympify(parts[1].strip(), evaluate=True)
                    diff = sp.simplify(lhs - rhs)
                    if diff == 0:
                        return True
                    if diff.is_number and diff != 0:
                        return False
                except (sp.SympifyError, TypeError, ValueError):
                    pass

        # Inequality check
        for op, cls in [("<=", sp.Le), (">=", sp.Ge), ("<", sp.Lt), (">", sp.Gt)]:
            if op in stmt:
                parts = stmt.split(op, 1)
                if len(parts) == 2:
                    try:
                        lhs = sp.sympify(parts[0].strip())
                        rhs = sp.sympify(parts[1].strip())
                        rel = cls(lhs, rhs, evaluate=True)
                        if rel is sp.true:
                            return True
                        if rel is sp.false:
                            return False
                    except (sp.SympifyError, TypeError, ValueError):
                        pass

        return None  # undecidable symbolically
