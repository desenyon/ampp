"""
Invariant / Monovariant Proposer — proof steps using invariants and monovariants.
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


class InvariantProposer(BaseProposer):
    name = "invariant"
    strategy_family = StrategyFamily.INVARIANT

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on INVARIANT / MONOVARIANT:\n"
                "- Identify a quantity preserved under the operations\n"
                "- Or identify a quantity that strictly increases/decreases\n"
                "- Prove the invariant/monovariant property\n"
                "- Use it to derive the target\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.PROPOSE_LEMMA,
                new_claims=(
                    f"Invariant identification for: {subgoal.statement}",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V1", "V2", "V3"),
                    success_criteria=(
                        "Invariant holds for all tested transitions"
                    ),
                    z3_encoding_hint=(
                        "Encode state transitions; assert invariant pre/post"
                    ),
                    falsification_bounds="Enumerate transitions for n ≤ 6",
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"n": 2},
                        description="Check invariant for n=2 transitions",
                    ),
                ),
                lean_stub=(
                    "-- Invariant lemma\n"
                    "theorem invariant_preserved (s : State) "
                    "(h : valid_transition s s') :\n"
                    "  inv s = inv s' := by\n"
                    "  sorry\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
