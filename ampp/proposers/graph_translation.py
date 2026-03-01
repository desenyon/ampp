"""
Graph Translation Proposer — proof steps by reinterpreting as graph problems.
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


class GraphTranslationProposer(BaseProposer):
    name = "graph_translation"
    strategy_family = StrategyFamily.GRAPH_TRANSLATION

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on GRAPH TRANSLATION:\n"
                "- Model the problem as a graph (vertices, edges)\n"
                "- Apply graph-theoretic results (Ramsey, Turán, etc.)\n"
                "- Translate combinatorial constraints to graph properties\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.INTRODUCE_DEFINITION,
                new_claims=(
                    f"Graph model for: {subgoal.statement}",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V1", "V3"),
                    success_criteria=(
                        "Graph model correctly encodes original problem"
                    ),
                    z3_encoding_hint=(
                        "Encode adjacency constraints; verify equivalence"
                    ),
                    falsification_bounds="Enumerate graphs on ≤ 6 vertices",
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"vertices": 4},
                        description="Verify graph model for 4 vertices",
                    ),
                ),
                lean_stub=(
                    "-- Graph translation\n"
                    "def problem_graph (n : ℕ) : SimpleGraph (Fin n) where\n"
                    "  Adj := sorry\n"
                    "  symm := sorry\n"
                    "  loopless := sorry\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
