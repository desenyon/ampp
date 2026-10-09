"""V3: diagnostic SMT checking of integer arithmetic.

Candidate success criteria are descriptions, never solver assumptions.
Only explicit caller-owned ``assumptions`` may constrain the solver; all must
parse and be jointly satisfiable before the negated claim is added.
"""

from __future__ import annotations

from typing import Any

from ampp.config import cfg
from ampp.schemas import StepCandidate
from ampp.verifiers.arithmetic import COMPARISONS, UnsupportedExpression, parse_relation
from ampp.verifiers.result import result


class Z3Verifier:
    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        try:
            import z3
        except ImportError:
            return result("unavailable", reason="z3_not_installed")
        unknown = False
        for claim in candidate.new_claims:
            checked, details = self._smt_check(claim.statement, z3, candidate, context)
            if checked is False:
                return result("failed", **details)
            unknown |= checked is None
            if checked is None:
                return result("inconclusive", **details)
        if unknown:
            return result("inconclusive", reason="Z3 did not decide every claim")
        return result("passed", method="V3_smt", z3_result="UNSAT", domain="integers")

    def _smt_check(
        self, statement: str, z3: Any, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool | None, dict[str, Any]]:
        solver = z3.Solver()
        solver.set("timeout", cfg.z3_timeout_ms)
        for assumption in context.get("assumptions", []):
            parsed = self._parse_z3_constraint(assumption, z3)
            if parsed is None:
                return None, {"reason": "Unsupported solver assumption"}
            solver.add(parsed)
        consistency = solver.check()
        if consistency != z3.sat:
            return None, {"reason": "Assumptions are inconsistent or undecidable"}
        negated = self._negate_claim(statement, z3)
        if negated is None:
            return None, {"reason": "Could not express claim in Z3"}
        solver.add(negated)
        checked = solver.check()
        if checked == z3.unsat:
            return True, {"z3_result": "UNSAT"}
        if checked == z3.sat:
            model = solver.model()
            return False, {
                "reason": "Z3 found a counterexample",
                "witness": {str(d): str(model[d]) for d in model.decls()},
            }
        return None, {"reason": solver.reason_unknown(), "z3_result": "UNKNOWN"}

    def _negate_claim(self, statement: str, z3: Any) -> Any | None:
        parsed = self._parse_z3_constraint(statement, z3)
        return None if parsed is None else z3.Not(parsed)

    def _parse_z3_constraint(self, constraint: str, z3: Any) -> Any | None:
        try:
            lhs, op, rhs = parse_relation(constraint, z3.IntVal, z3.Int)
            return COMPARISONS[op](lhs, rhs)
        except (UnsupportedExpression, TypeError, ValueError):
            return None
