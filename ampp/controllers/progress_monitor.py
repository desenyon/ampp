"""
Progress Metric Enforcement (Section 15)

Each iteration must achieve one of:
- Add verified claim
- Reduce subgoal count
- Shrink difficulty estimate
- Eliminate branch via counterexample
- Produce tighter canonical form

Otherwise strategy switch is forced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ampp.models.proof_state import ProofState

logger = logging.getLogger(__name__)


@dataclass
class ProgressSnapshot:
    """Snapshot of progress metrics at a point in time."""
    iteration: int
    verified_count: int
    open_subgoals: int
    rejected_count: int
    total_difficulty: float
    counterexamples: int
    state_hash: str


@dataclass
class ProgressResult:
    """Result of progress evaluation."""
    made_progress: bool
    progress_type: str  # What kind of progress was made
    details: str
    force_switch: bool  # True if strategy switch is required


class ProgressMonitor:
    """
    Monitors proof progress and enforces the progress-monotonic invariant.

    At each iteration, at least one of the following must occur:
    1. A new verified claim is added
    2. The number of open subgoals decreases
    3. Difficulty estimates shrink
    4. A branch is eliminated via counterexample
    5. A tighter canonical form is produced

    If none of these occur, a strategy switch is forced.
    """

    def __init__(self) -> None:
        self.history: list[ProgressSnapshot] = []
        self.stall_count: int = 0
        self.max_consecutive_stalls: int = 0

    def snapshot(
        self, iteration: int, state: ProofState
    ) -> ProgressSnapshot:
        """Take a snapshot of current progress metrics."""
        total_difficulty = sum(
            sg.difficulty_estimate for sg in state.open_subgoals
        )

        snap = ProgressSnapshot(
            iteration=iteration,
            verified_count=len(state.verified_claims),
            open_subgoals=len(state.open_subgoals),
            rejected_count=len(state.rejected_claims),
            total_difficulty=total_difficulty,
            counterexamples=len(state.counterexamples),
            state_hash=state.state_hash(),
        )

        self.history.append(snap)
        return snap

    def evaluate(
        self, iteration: int, state: ProofState
    ) -> ProgressResult:
        """
        Evaluate whether progress was made in this iteration.

        Compares current state to previous snapshot.
        """
        current = self.snapshot(iteration, state)

        if len(self.history) < 2:
            return ProgressResult(
                made_progress=True,
                progress_type="initial",
                details="First iteration — progress assumed",
                force_switch=False,
            )

        prev = self.history[-2]

        # Check each progress criterion
        progress_types: list[str] = []

        # 1. New verified claim
        if current.verified_count > prev.verified_count:
            progress_types.append(
                f"verified_claims: {prev.verified_count} → "
                f"{current.verified_count}"
            )

        # 2. Fewer open subgoals
        if current.open_subgoals < prev.open_subgoals:
            progress_types.append(
                f"open_subgoals: {prev.open_subgoals} → "
                f"{current.open_subgoals}"
            )

        # 3. Lower total difficulty
        if current.total_difficulty < prev.total_difficulty - 0.01:
            progress_types.append(
                f"difficulty: {prev.total_difficulty:.2f} → "
                f"{current.total_difficulty:.2f}"
            )

        # 4. New counterexample (eliminates a branch)
        if current.counterexamples > prev.counterexamples:
            progress_types.append(
                f"counterexamples: {prev.counterexamples} → "
                f"{current.counterexamples}"
            )

        # 5. More rejected claims (reduces search space)
        if current.rejected_count > prev.rejected_count:
            progress_types.append(
                f"rejected: {prev.rejected_count} → "
                f"{current.rejected_count}"
            )

        # 6. State changed at all
        if current.state_hash != prev.state_hash:
            if not progress_types:
                progress_types.append("state_changed")

        made_progress = len(progress_types) > 0

        if made_progress:
            self.stall_count = 0
            return ProgressResult(
                made_progress=True,
                progress_type="; ".join(progress_types),
                details=f"Progress at iteration {iteration}",
                force_switch=False,
            )
        else:
            self.stall_count += 1
            self.max_consecutive_stalls = max(
                self.max_consecutive_stalls, self.stall_count
            )

            logger.warning(
                "No progress at iteration %d (stall count: %d)",
                iteration,
                self.stall_count,
            )

            return ProgressResult(
                made_progress=False,
                progress_type="none",
                details=(
                    f"No progress for {self.stall_count} "
                    f"consecutive iterations"
                ),
                force_switch=self.stall_count >= 3,
            )

    def summary(self) -> dict[str, Any]:
        """Return a summary of progress history."""
        if not self.history:
            return {"iterations": 0}

        return {
            "iterations": len(self.history),
            "final_verified": self.history[-1].verified_count,
            "final_open_subgoals": self.history[-1].open_subgoals,
            "max_consecutive_stalls": self.max_consecutive_stalls,
            "total_stalls": sum(
                1
                for i in range(1, len(self.history))
                if self.history[i].state_hash
                == self.history[i - 1].state_hash
            ),
        }
