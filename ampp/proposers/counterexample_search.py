"""
Counterexample Search Proposer — generates proof steps by searching for
minimal counterexamples and using their non-existence as proof.
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


class CounterexampleSearchProposer(BaseProposer):
    name = "minimal_counterexample"
    strategy_family = StrategyFamily.MINIMAL_COUNTEREXAMPLE

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on MINIMAL COUNTEREXAMPLE METHOD:\n"
                "- Assume a minimal counterexample exists\n"
                "- Derive properties the minimal counterexample must have\n"
                "- Show these properties lead to contradiction\n"
                "- Or show a smaller counterexample must exist (contradiction)\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.PROPOSE_LEMMA,
                new_claims=(
                    f"No minimal counterexample exists for: "
                    f"{subgoal.statement}",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V1", "V3", "V5"),
                    success_criteria=(
                        "Exhaustive search finds no counterexample; "
                        "Z3 shows minimal case impossible"
                    ),
                    z3_encoding_hint=(
                        "Assert minimal counterexample; derive contradiction"
                    ),
                    falsification_bounds="Exhaustive search for n ≤ 12",
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"n": 1},
                        description="No counterexample at n=1",
                    ),
                    SmallCaseTest(
                        parameters={"n": 5},
                        description="No counterexample at n=5",
                    ),
                ),
                lean_stub=(
                    "-- Minimal counterexample method\n"
                    "theorem no_minimal_cex : ¬∃ n, "
                    "is_minimal_cex n := by\n"
                    "  intro ⟨n, hn⟩\n"
                    "  sorry\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
