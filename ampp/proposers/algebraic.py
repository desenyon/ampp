"""
Algebraic Normalization Proposer — proof steps via algebraic manipulation.
"""

from __future__ import annotations

from ampp.config import ActionType, StrategyFamily
from ampp.models.proof_state import ProofState
from ampp.models.state import FormalSpec, Subgoal
from ampp.models.step_candidate import (
    SmallCaseTest,
    StepCandidate,
    VerificationPlan,
)
from ampp.proposers.base import BaseProposer


class AlgebraicProposer(BaseProposer):
    name = "algebraic"
    strategy_family = StrategyFamily.ALGEBRAIC

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on ALGEBRAIC NORMALIZATION:\n"
                "- Rewrite expressions into canonical forms\n"
                "- Factor, expand, or simplify expressions\n"
                "- Apply known algebraic identities\n"
                "- Normalize inequalities\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.REWRITE,
                new_claims=(
                    f"Algebraic simplification of: {subgoal.statement}",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V2", "V3"),
                    success_criteria=(
                        "SymPy confirms algebraic equivalence"
                    ),
                    z3_encoding_hint=(
                        "Encode LHS and RHS; assert equality"
                    ),
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"n": 5},
                        description="Verify algebraic identity for n=5",
                    ),
                ),
                lean_stub=(
                    "-- Algebraic rewrite\n"
                    "theorem alg_rewrite : LHS = RHS := by\n"
                    "  ring\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
