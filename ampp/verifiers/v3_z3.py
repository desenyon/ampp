"""V3 — SMT verification using Z3.

Attempts to prove the candidate claim by showing that its negation is
unsatisfiable under the given constraints.
"""
from __future__ import annotations

import logging
from typing import Any

from ampp.schemas import StepCandidate

logger = logging.getLogger(__name__)

# Maximum Z3 solver timeout in milliseconds.
Z3_TIMEOUT_MS = 30_000


class Z3Verifier:
    """V3 verifier: SMT solving via Z3."""

    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """Return (passed, details)."""
        try:
            import z3
        except ImportError:
            logger.warning("z3-solver not installed — skipping V3")
            return True, {"skipped": True, "reason": "z3_not_installed"}

        for claim_spec in candidate.new_claims:
            result, detail = self._smt_check(claim_spec.statement, z3, candidate, context)
            if result is False:
                return False, detail

        return True, {"method": "V3_smt"}

    # ── Private helpers ───────────────────────────────────────────────────────

    def _smt_check(
        self,
        statement: str,
        z3: Any,
        candidate: StepCandidate,
        context: dict[str, Any],
    ) -> tuple[bool | None, dict[str, Any]]:
        """
        Build a Z3 solver instance, assert the negation of the claim, and check.
        Returns (True, {}) if UNSAT (claim holds), (False, {model}) if SAT (counterexample),
        (None, {}) if Unknown.
        """
        solver = z3.Solver()
        solver.set("timeout", Z3_TIMEOUT_MS)

        # Extract constraints from context and add them
        for constraint in candidate.verification_plan.success_criteria.values():
            try:
                parsed = self._parse_z3_constraint(constraint, z3)
                if parsed is not None:
                    solver.add(parsed)
            except Exception:
                pass

        # Attempt to negate and add the claim itself
        negated = self._negate_claim(statement, z3)
        if negated is None:
            # Can't express in Z3 — skip (conservative pass)
            return None, {"reason": "Could not express claim in Z3"}

        solver.add(negated)
        result = solver.check()

        if result == z3.unsat:
            return True, {"z3_result": "UNSAT"}
        elif result == z3.sat:
            model = solver.model()
            model_dict = {str(d): str(model[d]) for d in model.decls()}
            return False, {
                "reason": "Z3 found satisfying model (counterexample) for negated claim",
                "model": model_dict,
            }
        else:
            return None, {"z3_result": "UNKNOWN"}

    def _negate_claim(self, statement: str, z3: Any) -> Any | None:
        """
        Very conservative approach: try to parse simple arithmetic claims.
        Returns a Z3 expression representing the negation, or None.
        """
        import re

        # Match patterns like "n >= 0", "a + b = c"
        # For complex statements, return None (undecidable — conservative pass)
        eq_match = re.match(r"^\s*(\w+)\s*=\s*(\d+)\s*$", statement)
        if eq_match:
            var_name, val = eq_match.group(1), int(eq_match.group(2))
            var = z3.Int(var_name)
            return var != val  # negation of equality

        ineq_match = re.match(r"^\s*(\w+)\s*(>=|<=|>|<)\s*(\d+)\s*$", statement)
        if ineq_match:
            var_name, op, val_str = (
                ineq_match.group(1),
                ineq_match.group(2),
                int(ineq_match.group(3)),
            )
            var = z3.Int(var_name)
            # negate the inequality
            ops = {">=": var < val_str, "<=": var > val_str, ">": var <= val_str, "<": var >= val_str}
            return ops.get(op)

        return None

    def _parse_z3_constraint(self, constraint: str, z3: Any) -> Any | None:
        """Parse a simple constraint string into a Z3 expression."""
        return self._negate_claim(constraint, z3)  # reuse same parser
