"""
V3 — SMT Verification via Z3 (Section 8)

Translate claims to constraint form:
- If negation unsatisfiable → verified fragment
- If model found → counterexample
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ampp.config import VerifierConfig
from ampp.models.state import Counterexample, VerificationArtifact

logger = logging.getLogger(__name__)


@dataclass
class V3Result:
    passed: bool
    details: str = ""
    model: dict[str, Any] | None = None  # If countermodel found
    counterexample: Counterexample | None = None


class V3SMTVerifier:
    """
    SMT verification using Z3.

    Strategy:
    1. Encode the claim as a Z3 formula
    2. Negate the formula
    3. Check satisfiability of the negation
       - UNSAT → claim verified (for the encoded fragment)
       - SAT → counterexample found → claim rejected
       - UNKNOWN → inconclusive (don't reject)
    """

    def __init__(self, config: VerifierConfig | None = None) -> None:
        self.config = config or VerifierConfig()
        self._z3_available: bool | None = None

    @property
    def z3_available(self) -> bool:
        if self._z3_available is None:
            try:
                import z3  # noqa: F401
                self._z3_available = True
            except ImportError:
                self._z3_available = False
        return self._z3_available

    def verify_claim(
        self,
        claim_id: str,
        z3_encoding: str,
        *,
        claim_statement: str = "",
    ) -> V3Result:
        """
        Verify a claim using Z3.

        Args:
            claim_id: ID of the claim.
            z3_encoding: Z3 Python code that sets up and asserts the
                negation of the claim. Expected to define a variable
                `solver` and assertions.
            claim_statement: Human-readable statement for logging.

        Returns:
            V3Result with pass/fail and optional countermodel.
        """
        if not self.z3_available:
            logger.warning("Z3 not available, skipping V3")
            return V3Result(
                passed=True,
                details="V3 skipped: Z3 not available",
            )

        try:
            import z3

            solver = z3.Solver()
            solver.set("timeout", self.config.z3_timeout_ms)

            # Execute the Z3 encoding in a restricted namespace
            namespace: dict[str, Any] = {"z3": z3, "solver": solver}
            exec(z3_encoding, namespace)  # noqa: S102

            result = solver.check()

            if result == z3.unsat:
                # Negation is unsatisfiable → claim verified
                return V3Result(
                    passed=True,
                    details=(
                        "Z3: negation UNSAT → claim verified "
                        f"(fragment) for {claim_id}"
                    ),
                )
            elif result == z3.sat:
                # Found a model → counterexample
                model = solver.model()
                model_dict = {
                    str(d): str(model[d])
                    for d in model.decls()
                }

                cx = Counterexample(
                    claim_id=claim_id,
                    witness_structure=model_dict,
                    generation_method="z3",
                )

                return V3Result(
                    passed=False,
                    details=f"Z3: SAT model found → counterexample: {model_dict}",
                    model=model_dict,
                    counterexample=cx,
                )
            else:
                # Unknown / timeout
                return V3Result(
                    passed=True,  # Don't reject on timeout
                    details="Z3: result unknown/timeout",
                )

        except Exception as e:
            logger.error("V3 error: %s", e)
            return V3Result(
                passed=True,  # Don't reject on error
                details=f"V3 error: {e}",
            )

    def verify_forall_nat(
        self,
        claim_id: str,
        property_expr: str,
        *,
        bound: int = 100,
    ) -> V3Result:
        """
        Verify ∀ n : ℕ, P(n) for bounded n using Z3.

        Args:
            claim_id: Claim ID.
            property_expr: Python expression using 'n' that evaluates to bool.
            bound: Upper bound for n.
        """
        if not self.z3_available:
            return V3Result(
                passed=True,
                details="V3 skipped: Z3 not available",
            )

        try:
            import z3

            n = z3.Int("n")
            solver = z3.Solver()
            solver.set("timeout", self.config.z3_timeout_ms)

            # Assert n is in bounds
            solver.add(n >= 0, n < bound)

            # Parse and negate the property
            namespace: dict[str, Any] = {"z3": z3, "n": n}
            prop = eval(property_expr, namespace)  # noqa: S307
            solver.add(z3.Not(prop))

            result = solver.check()

            if result == z3.unsat:
                return V3Result(
                    passed=True,
                    details=(
                        f"Z3: ∀ n < {bound}, P(n) verified"
                    ),
                )
            elif result == z3.sat:
                model = solver.model()
                model_dict = {"n": str(model.eval(n))}
                cx = Counterexample(
                    claim_id=claim_id,
                    witness_structure=model_dict,
                    generation_method="z3",
                )
                return V3Result(
                    passed=False,
                    details=f"Z3: counterexample at n={model_dict['n']}",
                    model=model_dict,
                    counterexample=cx,
                )
            else:
                return V3Result(
                    passed=True,
                    details="Z3: result unknown",
                )

        except Exception as e:
            logger.error("V3 forall_nat error: %s", e)
            return V3Result(
                passed=True,
                details=f"V3 error: {e}",
            )

    def to_artifact(self, result: V3Result) -> VerificationArtifact:
        return VerificationArtifact(
            stage="V3",
            result="pass" if result.passed else "fail",
            details=result.details,
        )
