"""
Planner (Section 5)

Generates a dependency DAG of subgoals from the formal specification.
Each subgoal includes statement, dependencies, expected strategy,
and verification plan.

Subgoals ranked by: impact_score / estimated_complexity
"""

from __future__ import annotations

import logging
from typing import Any

from ampp.config import StrategyFamily
from ampp.models.proof_state import ProofState
from ampp.models.state import Claim, FormalSpec, Subgoal, _new_id

logger = logging.getLogger(__name__)


class SubgoalNode:
    """A node in the subgoal dependency DAG."""

    def __init__(self, subgoal: Subgoal) -> None:
        self.subgoal = subgoal
        self.children: list[SubgoalNode] = []
        self.parents: list[SubgoalNode] = []

    def add_child(self, child: SubgoalNode) -> None:
        self.children.append(child)
        child.parents.append(self)


class SubgoalDAG:
    """Dependency DAG of subgoals."""

    def __init__(self) -> None:
        self.nodes: dict[str, SubgoalNode] = {}
        self.root_ids: list[str] = []

    def add_node(self, subgoal: Subgoal) -> SubgoalNode:
        node = SubgoalNode(subgoal)
        self.nodes[subgoal.id] = node
        return node

    def add_edge(self, parent_id: str, child_id: str) -> None:
        parent = self.nodes[parent_id]
        child = self.nodes[child_id]
        parent.add_child(child)

    def topological_order(self) -> list[Subgoal]:
        """Return subgoals in topological order (leaves first)."""
        visited: set[str] = set()
        result: list[Subgoal] = []

        def dfs(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            node = self.nodes[node_id]
            for child in node.children:
                dfs(child.subgoal.id)
            result.append(node.subgoal)

        for nid in self.nodes:
            dfs(nid)

        return result

    def frontier(self, resolved: set[str]) -> list[Subgoal]:
        """
        Return subgoals whose blockers are all resolved.
        These are the actionable frontier.
        """
        frontier: list[Subgoal] = []
        for node in self.nodes.values():
            sg = node.subgoal
            if sg.resolved:
                continue
            if all(b in resolved for b in sg.blockers):
                frontier.append(sg)
        # Sort by effective priority (impact / complexity)
        frontier.sort(key=lambda sg: -sg.effective_priority)
        return frontier


class Planner:
    """
    Generates subgoal DAGs from formal specifications.

    Uses LLM assistance to decompose problems into verifiable micro-steps,
    or falls back to heuristic decomposition.
    """

    def __init__(self, llm_assist: Any | None = None) -> None:
        self.llm_assist = llm_assist

    def plan(
        self,
        spec: FormalSpec,
        state: ProofState,
    ) -> SubgoalDAG:
        """
        Generate a subgoal DAG for the given formal specification.

        Args:
            spec: The normalized formal specification.
            state: Current proof state (for incremental re-planning).

        Returns:
            A SubgoalDAG with subgoals ready for the proposer ensemble.
        """
        logger.info("Planning subgoals for problem %s", spec.problem_id)

        if self.llm_assist is not None:
            return self._llm_plan(spec, state)

        return self._heuristic_plan(spec, state)

    def _llm_plan(
        self,
        spec: FormalSpec,
        state: ProofState,
    ) -> SubgoalDAG:
        """Use LLM to decompose the problem into subgoals."""
        import json

        verified_stmts = [c.statement for c in state.verified_claims]
        open_sgs = [sg.statement for sg in state.open_subgoals]

        prompt = (
            "You are a mathematical proof planner. Decompose the following "
            "problem into a sequence of verifiable subgoals (micro-lemmas).\n\n"
            f"Problem (canonical form):\n{spec.canonical_form}\n\n"
            f"Already verified:\n{json.dumps(verified_stmts)}\n\n"
            f"Open subgoals:\n{json.dumps(open_sgs)}\n\n"
            "For each subgoal, provide:\n"
            "- statement: The precise mathematical claim\n"
            "- dependencies: IDs of subgoals this depends on (use indices)\n"
            "- strategy: One of [induction, strong_induction, extremal, "
            "invariant, counting, construction, contradiction, algebraic, "
            "graph_translation, minimal_counterexample]\n"
            "- difficulty: Estimated difficulty 0.1 to 10.0\n"
            "- impact: Impact score 0.1 to 10.0\n\n"
            "Return JSON: {subgoals: [{statement, dependencies, strategy, "
            "difficulty, impact}]}"
        )

        try:
            response = self.llm_assist(prompt)  # type: ignore[misc]
        except Exception:
            logger.warning("LLM planning call failed, using heuristic fallback")
            return self._heuristic_plan(spec, state)

        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM planning failed, using heuristic fallback")
            return self._heuristic_plan(spec, state)

        dag = SubgoalDAG()
        subgoal_ids: list[str] = []

        for i, sg_data in enumerate(data.get("subgoals", [])):
            sg_id = _new_id()
            subgoal_ids.append(sg_id)

            # Map dependency indices to IDs
            dep_indices = sg_data.get("dependencies", [])
            blockers = tuple(
                subgoal_ids[idx]
                for idx in dep_indices
                if idx < len(subgoal_ids)
            )

            sg = Subgoal(
                id=sg_id,
                statement=sg_data.get("statement", ""),
                priority_score=float(sg_data.get("impact", 1.0)),
                difficulty_estimate=float(sg_data.get("difficulty", 1.0)),
                blockers=blockers,
                expected_strategy=sg_data.get("strategy", ""),
            )
            dag.add_node(sg)

        # Add edges from dependencies
        for i, sg_id in enumerate(subgoal_ids):
            sg_data = data["subgoals"][i]
            for dep_idx in sg_data.get("dependencies", []):
                if dep_idx < len(subgoal_ids):
                    dag.add_edge(subgoal_ids[dep_idx], sg_id)

        if not dag.nodes:
            return self._heuristic_plan(spec, state)

        logger.info("LLM plan produced %d subgoals", len(dag.nodes))
        return dag

    def _heuristic_plan(
        self,
        spec: FormalSpec,
        state: ProofState,
    ) -> SubgoalDAG:
        """
        Rule-based fallback planning.

        Creates a simple linear decomposition:
        1. Base case / smallest instance
        2. Key lemma
        3. Main theorem
        """
        dag = SubgoalDAG()

        # Subgoal 1: Establish base case / small instance
        base_id = _new_id()
        base_sg = Subgoal(
            id=base_id,
            statement=f"Base case verification for: {spec.target_statement}",
            priority_score=3.0,
            difficulty_estimate=1.0,
            expected_strategy=StrategyFamily.CONSTRUCTION,
            verification_plan="Enumerate small cases; verify by exhaustion.",
        )
        dag.add_node(base_sg)

        # Subgoal 2: Key structural lemma
        lemma_id = _new_id()
        lemma_sg = Subgoal(
            id=lemma_id,
            statement=f"Key lemma for: {spec.target_statement}",
            priority_score=5.0,
            difficulty_estimate=3.0,
            blockers=(base_id,),
            expected_strategy=StrategyFamily.INDUCTION,
            verification_plan=(
                "Verify via symbolic computation (V2) and SMT (V3)."
            ),
        )
        dag.add_node(lemma_sg)
        dag.add_edge(base_id, lemma_id)

        # Subgoal 3: Main theorem
        theorem_id = _new_id()
        theorem_sg = Subgoal(
            id=theorem_id,
            statement=spec.target_statement,
            priority_score=10.0,
            difficulty_estimate=5.0,
            blockers=(lemma_id,),
            expected_strategy=StrategyFamily.INDUCTION,
            verification_plan="Full cascade V0-V5; Lean compilation required.",
        )
        dag.add_node(theorem_sg)
        dag.add_edge(lemma_id, theorem_id)

        logger.info("Heuristic plan: 3 subgoals (base → lemma → theorem)")
        return dag

    def replan(
        self,
        spec: FormalSpec,
        state: ProofState,
        failure_context: str = "",
    ) -> SubgoalDAG:
        """
        Re-plan after failures, incorporating feedback.

        Args:
            spec: The formal specification.
            state: Current proof state.
            failure_context: Description of recent failures.

        Returns:
            Updated SubgoalDAG.
        """
        logger.info("Re-planning with failure context")

        if self.llm_assist is not None:
            import json

            prompt = (
                "Re-plan the proof after these failures:\n"
                f"{failure_context}\n\n"
                f"Problem: {spec.canonical_form}\n"
                f"Verified so far: "
                f"{json.dumps([c.statement for c in state.verified_claims])}\n"
                f"Failed attempts: {len(state.attempts)}\n"
                f"Failure distribution: "
                f"{json.dumps(state.failure_modes())}\n\n"
                "Generate new subgoals avoiding previous failure patterns. "
                "Return JSON: {subgoals: [{statement, dependencies, strategy, "
                "difficulty, impact}]}"
            )
            response = self.llm_assist(prompt)
            try:
                data = json.loads(response)
                dag = SubgoalDAG()
                for sg_data in data.get("subgoals", []):
                    sg = Subgoal(
                        id=_new_id(),
                        statement=sg_data.get("statement", ""),
                        priority_score=float(sg_data.get("impact", 1.0)),
                        difficulty_estimate=float(
                            sg_data.get("difficulty", 1.0)
                        ),
                        expected_strategy=sg_data.get("strategy", ""),
                    )
                    dag.add_node(sg)
                if dag.nodes:
                    return dag
            except (json.JSONDecodeError, TypeError):
                pass

        return self._heuristic_plan(spec, state)
