"""
Beam Search Manager (Section 11)

Maintains 3–6 active proof states.

Ranking factors:
- Verified claim count
- Subgoal reduction rate
- Structural diversity
- Branching control
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ampp.config import BeamConfig
from ampp.models.proof_state import ProofState

logger = logging.getLogger(__name__)


@dataclass
class BeamScore:
    """Score for a beam state."""
    branch_id: str
    verified_count: int
    open_subgoals: int
    total_attempts: int
    composite_score: float
    diversity_hash: str


class BeamManager:
    """
    Manages multiple parallel proof states (beam search).

    Prevents premature strategic commitment by maintaining diverse
    proof paths. Prunes low-scoring beams and forks promising ones.
    """

    def __init__(self, config: BeamConfig | None = None) -> None:
        self.config = config or BeamConfig()
        self.beams: dict[str, ProofState] = {}
        self._beam_counter = 0

    def initialize(self, initial_state: ProofState) -> list[str]:
        """
        Initialize beams from an initial state.

        Creates min_beams copies with different branch IDs.
        """
        branch_ids: list[str] = []
        for i in range(self.config.min_beams):
            bid = self._next_branch_id()
            beam = initial_state.clone(bid)
            self.beams[bid] = beam
            branch_ids.append(bid)

        logger.info(
            "BeamManager: initialized %d beams", len(branch_ids)
        )
        return branch_ids

    def get_beam(self, branch_id: str) -> ProofState | None:
        return self.beams.get(branch_id)

    def all_beams(self) -> list[ProofState]:
        return list(self.beams.values())

    def score_beams(self) -> list[BeamScore]:
        """Score all beams and return sorted (best first)."""
        scores: list[BeamScore] = []

        for bid, state in self.beams.items():
            verified = len(state.verified_claims)
            open_sg = len(state.open_subgoals)
            attempts = len(state.attempts)

            # Composite: more verified claims + fewer open subgoals = better
            composite = (
                verified * 3.0
                - open_sg * 1.0
                - attempts * 0.1
            )

            scores.append(
                BeamScore(
                    branch_id=bid,
                    verified_count=verified,
                    open_subgoals=open_sg,
                    total_attempts=attempts,
                    composite_score=composite,
                    diversity_hash=state.state_hash(),
                )
            )

        scores.sort(key=lambda s: -s.composite_score)
        return scores

    def prune(self) -> list[str]:
        """
        Prune low-scoring beams, keeping at least min_beams.

        Returns list of pruned branch IDs.
        """
        scores = self.score_beams()

        if len(scores) <= self.config.min_beams:
            return []

        # Keep top beams, ensure diversity
        keep: set[str] = set()
        seen_hashes: set[str] = set()

        for score in scores:
            if len(keep) >= self.config.max_beams:
                break

            # Diversity check
            if score.diversity_hash in seen_hashes:
                if len(keep) >= self.config.min_beams:
                    continue  # Skip duplicate
            seen_hashes.add(score.diversity_hash)
            keep.add(score.branch_id)

        # Ensure minimum
        for score in scores:
            if len(keep) >= self.config.min_beams:
                break
            keep.add(score.branch_id)

        # Remove pruned beams
        pruned: list[str] = []
        for bid in list(self.beams.keys()):
            if bid not in keep:
                del self.beams[bid]
                pruned.append(bid)

        if pruned:
            logger.info(
                "BeamManager: pruned %d beams: %s",
                len(pruned),
                pruned,
            )

        return pruned

    def fork(self, branch_id: str) -> str | None:
        """
        Fork a beam state to explore an alternative path.

        Returns the new branch ID, or None if max beams reached.
        """
        if len(self.beams) >= self.config.max_beams:
            logger.debug("BeamManager: max beams reached, cannot fork")
            return None

        source = self.beams.get(branch_id)
        if source is None:
            return None

        new_bid = self._next_branch_id()
        self.beams[new_bid] = source.clone(new_bid)

        logger.info(
            "BeamManager: forked %s → %s", branch_id, new_bid
        )
        return new_bid

    def best_beam(self) -> str | None:
        """Return the branch ID of the highest-scoring beam."""
        scores = self.score_beams()
        if not scores:
            return None
        return scores[0].branch_id

    def is_diverse(self) -> bool:
        """Check if beams are sufficiently diverse."""
        hashes = [state.state_hash() for state in self.beams.values()]
        unique_ratio = len(set(hashes)) / max(len(hashes), 1)
        return unique_ratio >= self.config.diversity_threshold

    def _next_branch_id(self) -> str:
        self._beam_counter += 1
        return f"beam_{self._beam_counter:03d}"
