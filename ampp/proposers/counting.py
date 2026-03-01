"""
Double Counting Proposer — proof steps using combinatorial double counting.
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


class CountingProposer(BaseProposer):
    name = "counting"
    strategy_family = StrategyFamily.COUNTING

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on DOUBLE COUNTING:\n"
                "- Identify a set S that can be counted two ways\n"
                "- Express |S| using method 1\n"
                "- Express |S| using method 2\n"
                "- Equate or bound the two expressions\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.PROPOSE_LEMMA,
                new_claims=(
                    f"Double counting identity for: {subgoal.statement}",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V1", "V2"),
                    success_criteria="Both counting methods agree for all n ≤ N",
                    falsification_bounds="n ≤ 8",
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"n": 4},
                        description="Verify double counting for n=4",
                    ),
                ),
                lean_stub=(
                    "-- Double counting\n"
                    "theorem double_count (S : Finset (α × β)) :\n"
                    "  (∑ a, (S.filter (·.1 = a)).card) = S.card := by\n"
                    "  sorry\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
