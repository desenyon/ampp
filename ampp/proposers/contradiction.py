"""
Contradiction Proposer — proof steps via proof by contradiction.
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


class ContradictionProposer(BaseProposer):
    name = "contradiction"
    strategy_family = StrategyFamily.CONTRADICTION

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on PROOF BY CONTRADICTION:\n"
                "- Assume the negation of the target\n"
                "- Derive a logical contradiction\n"
                "- State the negation explicitly\n"
                "- Identify the contradiction clearly\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.PROPOSE_LEMMA,
                new_claims=(
                    f"Contradiction: ¬({subgoal.statement}) leads to absurdity",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V3", "V4", "V5"),
                    success_criteria=(
                        "Z3 shows negation is unsatisfiable, or "
                        "Lean compiles by_contra proof"
                    ),
                    z3_encoding_hint=(
                        "Assert negation of target; check UNSAT"
                    ),
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"n": 3},
                        description="Verify negation fails for n=3",
                    ),
                ),
                lean_stub=(
                    "-- Proof by contradiction\n"
                    "theorem target : P := by\n"
                    "  by_contra h\n"
                    "  sorry\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
