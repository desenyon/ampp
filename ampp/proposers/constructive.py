"""
Constructive Method Proposer — proof steps by constructing witnesses.
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


class ConstructiveProposer(BaseProposer):
    name = "constructive"
    strategy_family = StrategyFamily.CONSTRUCTION

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on CONSTRUCTIVE METHOD:\n"
                "- Explicitly construct the object claimed to exist\n"
                "- Provide the construction algorithm or formula\n"
                "- Verify it satisfies all required properties\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.CONSTRUCT_WITNESS,
                new_claims=(
                    f"Explicit construction for: {subgoal.statement}",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V1", "V2", "V3"),
                    success_criteria=(
                        "Constructed object satisfies all required properties"
                    ),
                    falsification_bounds="Verify construction for n ≤ 10",
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"n": 3},
                        description="Construct and verify for n=3",
                    ),
                ),
                lean_stub=(
                    "-- Constructive witness\n"
                    "theorem exists_witness : ∃ x, P x := by\n"
                    "  exact ⟨witness, proof⟩\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
