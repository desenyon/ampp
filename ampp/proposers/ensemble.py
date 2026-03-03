"""ProposerEnsemble — runs all strategy proposers and returns ranked candidates.

The ensemble:
1. Fans out to all proposers using the current strategy weights.
2. Deduplicates by candidate_hash.
3. Passes results through the RubricAgent for triage.
4. Returns the ranked, rubric-approved list.
"""
from __future__ import annotations

import logging
from typing import Any

from ampp.proposers.base import BaseProposer
from ampp.proposers.specializations import (
    AlgebraicNormalizationProposer,
    ConstructiveProposer,
    DoubleCountingProposer,
    ExtremalProposer,
    InductionProposer,
)
from ampp.schemas import StepCandidate, StrategyFamily

logger = logging.getLogger(__name__)


class ProposerEnsemble:
    """Coordinates all proposer specialisations."""

    def __init__(self, rubric_agent: Any = None) -> None:
        self._proposers: list[BaseProposer] = [
            InductionProposer(),
            ExtremalProposer(),
            DoubleCountingProposer(),
            ConstructiveProposer(),
            AlgebraicNormalizationProposer(),
        ]
        self._rubric = rubric_agent
        # Weight vector over strategy families (updated by RubricAgent)
        self._weights: dict[StrategyFamily, float] = {
            p.strategy_family: 1.0 for p in self._proposers
        }

    def update_weights(self, new_weights: dict[str, float]) -> None:
        """Update strategy weights from RubricAgent feedback."""
        for k, v in new_weights.items():
            try:
                self._weights[StrategyFamily(k)] = max(0.0, v)
            except ValueError:
                pass

    def propose(
        self,
        subgoal_id: str,
        branch_id: str,
        spec: dict[str, Any],
        verified_claims: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
        rejected_hashes: set[str] | None = None,
    ) -> list[StepCandidate]:
        """Run all proposers, deduplicate, triage, and rank."""
        raw: list[StepCandidate] = []
        rejected_hashes = rejected_hashes or set()

        # Sort proposers by weight (descending)
        sorted_proposers = sorted(
            self._proposers,
            key=lambda p: self._weights.get(p.strategy_family, 1.0),
            reverse=True,
        )

        for proposer in sorted_proposers:
            weight = self._weights.get(proposer.strategy_family, 1.0)
            if weight <= 0.0:
                logger.debug("Skipping %s (weight=0)", proposer.strategy_family)
                continue
            try:
                candidates = proposer.propose(
                    subgoal_id=subgoal_id,
                    branch_id=branch_id,
                    spec=spec,
                    verified_claims=verified_claims,
                    attempts=attempts,
                )
                raw.extend(candidates)
            except Exception as exc:
                logger.warning("Proposer %s failed: %s", proposer.strategy_family, exc)

        # Deduplicate by candidate_hash
        seen: set[str] = set()
        unique: list[StepCandidate] = []
        for cand in raw:
            if cand.candidate_hash in seen or cand.candidate_hash in rejected_hashes:
                continue
            seen.add(cand.candidate_hash)
            unique.append(cand)

        # Rubric triage
        if self._rubric is not None:
            unique = self._rubric.triage(unique, attempts)

        logger.info(
            "Ensemble produced %d candidates for subgoal %s", len(unique), subgoal_id
        )
        return unique
