"""
Extremal Principle Proposer — proof steps using extremal/minimal elements.
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


class ExtremalProposer(BaseProposer):
    name = "extremal"
    strategy_family = StrategyFamily.EXTREMAL

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on EXTREMAL PRINCIPLE:\n"
                "- Identify a quantity to extremize (max/min element)\n"
                "- Consider the element with the extremal property\n"
                "- Derive a contradiction or structure from extremality\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.BOUND_ARGUMENT,
                new_claims=(
                    f"Extremal element existence for: {subgoal.statement}",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V1", "V3", "V5"),
                    success_criteria=(
                        "Z3 verifies extremal element properties"
                    ),
                    z3_encoding_hint=(
                        "Define ordering, assert existence of max/min"
                    ),
                    falsification_bounds="n ≤ 8",
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"n": 3},
                        description="Verify extremal element for n=3",
                    ),
                ),
                lean_stub=(
                    "-- Extremal principle application\n"
                    "theorem extremal_exists (S : Finset ℕ) "
                    "(hne : S.Nonempty) :\n"
                    "  ∃ m ∈ S, ∀ x ∈ S, x ≤ m := by\n"
                    "  exact S.exists_max_image id hne\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
