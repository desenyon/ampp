"""V2: diagnostic polynomial identity and inequality checks over integers."""

from __future__ import annotations

from typing import Any

from ampp.schemas import StepCandidate
from ampp.verifiers.arithmetic import COMPARISONS, UnsupportedExpression, parse_relation
from ampp.verifiers.result import result


class SymPyVerifier:
    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        try:
            import sympy as sp
        except ImportError:
            return result("unavailable", reason="sympy_not_installed")
        unknown = False
        for claim in candidate.new_claims:
            checked = self._check_statement(claim.statement, sp)
            if checked is False:
                return result(
                    "failed", reason=f"SymPy refuted: {claim.statement}", statement=claim.statement
                )
            unknown |= checked is None
        if unknown:
            return result("inconclusive", reason="Unsupported or undecidable symbolic statement")
        return result("passed", method="V2_symbolic", domain="integers")

    def _check_statement(self, statement: str, sp: Any) -> bool | None:
        try:
            lhs, op, rhs = parse_relation(
                statement, sp.Integer, lambda name: sp.Symbol(name, integer=True)
            )
            if op in ("=", "==", "!="):
                diff = sp.expand(lhs - rhs)
                if diff == 0:
                    return op != "!="
                if diff.is_number:
                    return op == "!="
                return None
            relation = COMPARISONS[op](lhs, rhs)
            if relation is sp.true:
                return True
            if relation is sp.false:
                return False
        except (UnsupportedExpression, TypeError, ValueError):
            return None
        return None
