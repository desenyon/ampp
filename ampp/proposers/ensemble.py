"""
Proposer Ensemble (Section 6)

Coordinates multiple specialized proposers operating in parallel.
Each proposer outputs structured StepCandidate objects only.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ampp.config import StrategyFamily
from ampp.models.proof_state import ProofState
from ampp.models.state import FormalSpec, Subgoal
from ampp.models.step_candidate import StepCandidate
from ampp.proposers.algebraic import AlgebraicProposer
from ampp.proposers.base import BaseProposer
from ampp.proposers.constructive import ConstructiveProposer
from ampp.proposers.contradiction import ContradictionProposer
from ampp.proposers.counterexample_search import CounterexampleSearchProposer
from ampp.proposers.counting import CountingProposer
from ampp.proposers.extremal import ExtremalProposer
from ampp.proposers.graph_translation import GraphTranslationProposer
from ampp.proposers.induction import InductionProposer, StrongInductionProposer
from ampp.proposers.invariant import InvariantProposer

logger = logging.getLogger(__name__)


class ProposerEnsemble:
    """
    Manages the full set of specialized proposers.

    Proposers run in parallel. Strategy weights control which proposers
    are prioritized. All outputs are StepCandidate objects.
    """

    def __init__(
        self,
        llm_assist: Any | None = None,
        max_workers: int = 4,
    ) -> None:
        self.llm_assist = llm_assist
        self.max_workers = max_workers

        # Initialize all proposers
        self.proposers: dict[str, BaseProposer] = {
            StrategyFamily.INDUCTION: InductionProposer(llm_assist),
            StrategyFamily.STRONG_INDUCTION: StrongInductionProposer(
                llm_assist
            ),
            StrategyFamily.EXTREMAL: ExtremalProposer(llm_assist),
            StrategyFamily.INVARIANT: InvariantProposer(llm_assist),
            StrategyFamily.COUNTING: CountingProposer(llm_assist),
            StrategyFamily.CONSTRUCTION: ConstructiveProposer(llm_assist),
            StrategyFamily.CONTRADICTION: ContradictionProposer(llm_assist),
            StrategyFamily.ALGEBRAIC: AlgebraicProposer(llm_assist),
            StrategyFamily.GRAPH_TRANSLATION: GraphTranslationProposer(
                llm_assist
            ),
            StrategyFamily.MINIMAL_COUNTEREXAMPLE: (
                CounterexampleSearchProposer(llm_assist)
            ),
        }

        # Strategy weights (updated by Rubric Agent)
        self.weights: dict[str, float] = {
            k: 1.0 for k in self.proposers
        }

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
        *,
        active_strategies: list[str] | None = None,
    ) -> list[StepCandidate]:
        """
        Run all active proposers and collect StepCandidate objects.

        Args:
            subgoal: The subgoal to address.
            spec: The formal specification.
            state: Current proof state.
            active_strategies: Strategy families to use. If None, use all
                with positive weight.

        Returns:
            Merged list of StepCandidate objects from all proposers.
        """
        if active_strategies is None:
            active_strategies = [
                k for k, w in self.weights.items() if w > 0
            ]

        # Sort by weight (highest first)
        active_strategies.sort(key=lambda s: -self.weights.get(s, 0))

        logger.info(
            "Ensemble proposing for subgoal %s with %d strategies",
            subgoal.id,
            len(active_strategies),
        )

        all_candidates: list[StepCandidate] = []

        # Run proposers in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for strategy in active_strategies:
                proposer = self.proposers.get(strategy)
                if proposer is None:
                    continue
                future = executor.submit(
                    proposer.propose, subgoal, spec, state
                )
                futures[future] = strategy

            for future in as_completed(futures):
                strategy = futures[future]
                try:
                    candidates = future.result()
                    logger.info(
                        "Proposer %s produced %d candidates",
                        strategy,
                        len(candidates),
                    )
                    all_candidates.extend(candidates)
                except Exception as e:
                    logger.error(
                        "Proposer %s failed: %s", strategy, e
                    )

        logger.info(
            "Ensemble total: %d candidates", len(all_candidates)
        )
        return all_candidates

    def update_weights(self, weights: dict[str, float]) -> None:
        """Update strategy weights (called by Rubric Agent)."""
        self.weights.update(weights)
        logger.info("Strategy weights updated: %s", self.weights)

    def disable_strategy(self, strategy: str) -> None:
        """Set weight to zero for a strategy."""
        self.weights[strategy] = 0.0

    def get_active_proposers(self) -> list[str]:
        """Return names of proposers with positive weight."""
        return [k for k, w in self.weights.items() if w > 0]
