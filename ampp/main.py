"""
AMPP — Autonomous Mathematical Proof Pipeline
Main Orchestrator Loop (Sections 2, 15, 19)

Pipeline flow:
    Problem Input → Normalizer → FormalSpec → Planner → Proposer Ensemble
    → Rubric Agent filter → Verification Cascade → Lean Gate
    → Two-Phase Commit → State Update → Loop

Parallel subsystems:
    • Counterexample Engine
    • Conjecture Mining Engine
    • Strategy Switching Controller
    • Beam State Manager
    • Lemma Minimizer

Termination conditions (Section 19):
    1. Target theorem verified (Lean success), OR
    2. Proof reduced to finite exhaustive verification, OR
    3. Explicit declaration of incompleteness with full artifact log.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Callable

from ampp.artifacts.generator import ArtifactGenerator
from ampp.commit.two_phase import TwoPhaseCommit
from ampp.config import (
    ClaimStatus,
    ClaimType,
    PipelineConfig,
    StrategyFamily,
)
from ampp.controllers.beam_manager import BeamManager
from ampp.controllers.progress_monitor import ProgressMonitor
from ampp.controllers.rubric_agent import RubricAgent
from ampp.controllers.strategy_controller import StrategyController
from ampp.engines.conjecture_miner import ConjectureMiner
from ampp.engines.counterexample_refiner import CounterexampleRefiner
from ampp.engines.lemma_minimizer import LemmaMinimizer
from ampp.models.proof_state import ProofState
from ampp.models.state import Claim, FormalSpec, _new_id
from ampp.models.step_candidate import StepCandidate
from ampp.normalizer.normalizer import Normalizer
from ampp.planner.planner import Planner
from ampp.proposers.ensemble import ProposerEnsemble
from ampp.utils.hashing import compute_hash
from ampp.utils.pipeline_logging import PipelineLogger
from ampp.verification.cascade import VerificationCascade

logger = logging.getLogger(__name__)


class Pipeline:
    """
    The top-level AMPP orchestrator.

    Ties together all subsystems and drives the proof loop according
    to the architecture defined in CLAUDE.md.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        *,
        llm_assist: Any | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.llm_assist = llm_assist

        # ── Seed for reproducibility (Section 16) ─────────────────
        random.seed(self.config.global_seed)

        # ── Logging ───────────────────────────────────────────────
        self.logger = PipelineLogger(self.config.log_path)

        # ── Core components ───────────────────────────────────────
        self.normalizer = Normalizer()
        self.planner = Planner(llm_assist=llm_assist)
        self.ensemble = ProposerEnsemble(llm_assist=llm_assist)
        self.cascade = VerificationCascade(self.config.verifier)
        self.committer = TwoPhaseCommit(
            log_dir=str(self.config.log_path)
        )

        # ── Controllers ──────────────────────────────────────────
        self.rubric = RubricAgent(self.config.rubric)
        self.strategy_ctrl = StrategyController(self.config.strategy)
        self.progress = ProgressMonitor()
        self.beam_mgr = BeamManager(self.config.beam)

        # ── Engines ──────────────────────────────────────────────
        self.minimizer = LemmaMinimizer(llm_assist=llm_assist)
        self.refiner = CounterexampleRefiner(llm_assist=llm_assist)
        self.miner = ConjectureMiner(
            max_n=self.config.verifier.max_exhaustive_n
        )

        # ── Artifact generator ───────────────────────────────────
        self.artifact_gen = ArtifactGenerator(self.config.output_path)

        # ── Runtime state ────────────────────────────────────────
        self._iteration = 0
        self._start_time: float = 0.0
        self._events: list[dict[str, Any]] = []

    # ═════════════════════════════════════════════════════════════
    # Public API
    # ═════════════════════════════════════════════════════════════

    def run(
        self,
        problem_id: str,
        raw_statement: str,
        *,
        predicate: Callable[..., bool] | None = None,
        domain: dict[str, Any] | None = None,
        z3_encoding: str = "",
        tptp_problem: str = "",
    ) -> dict[str, Path]:
        """
        Execute the full proof pipeline on a problem.

        Args:
            problem_id: Unique identifier for the problem.
            raw_statement: The raw mathematical problem statement.
            predicate: Optional callable for counterexample testing.
            domain: Variable domain dict for counterexample search.
            z3_encoding: Optional Z3 encoding of the claim.
            tptp_problem: Optional TPTP encoding for ATP.

        Returns:
            Dict mapping artifact names to file paths.
        """
        self._start_time = time.time()
        self.logger.log_event("pipeline_start", {
            "problem_id": problem_id,
            "config": self._serialize_config(),
        })

        # ── Step 1: Normalize ─────────────────────────────────────
        spec = self._normalize(problem_id, raw_statement)

        # ── Step 2: Initialize proof state and beams ──────────────
        state = ProofState(formal_spec=spec)
        beam_ids = self.beam_mgr.initialize(state)
        logger.info("Initialized %d beams", len(beam_ids))

        # ── Step 3: Plan subgoals ─────────────────────────────────
        dag = self.planner.plan(spec, state)
        for sg in dag.topological_order():
            state.add_subgoal(sg)
            # Propagate to all beam states
            for bid in beam_ids:
                beam = self.beam_mgr.get_beam(bid)
                if beam:
                    beam.add_subgoal(sg)

        logger.info(
            "Plan: %d subgoals created", len(state.subgoals)
        )

        # ── Main loop ────────────────────────────────────────────
        while not self._should_terminate(state):
            self._iteration += 1
            self.logger.log_event("iteration_start", {
                "iteration": self._iteration,
                "verified": len(state.verified_claims),
                "open_subgoals": len(state.open_subgoals),
            })

            # Work on the best beam
            best_bid = self.beam_mgr.best_beam()
            if best_bid is None:
                logger.error("No active beams — aborting")
                break
            active_state = self.beam_mgr.get_beam(best_bid)
            if active_state is None:
                break

            made_progress = self._run_iteration(
                active_state,
                spec,
                dag,
                predicate=predicate,
                domain=domain,
                z3_encoding=z3_encoding,
                tptp_problem=tptp_problem,
            )

            # ── Progress monitoring (Section 15) ──────────────────
            snap = self.progress.snapshot(self._iteration, active_state)
            progress_result = self.progress.evaluate(self._iteration, active_state)

            if not progress_result.made_progress:
                logger.warning(
                    "No progress at iteration %d: %s",
                    self._iteration,
                    progress_result.details,
                )
                # Force strategy switch
                if progress_result.force_switch:
                    decision = self.strategy_ctrl.evaluate(
                        active_state,
                        last_strategy=self.strategy_ctrl.current_strategy,
                    )
                    if decision.should_switch:
                        self.strategy_ctrl.current_strategy = (
                            decision.recommended_strategy
                        )
                        logger.info(
                            "Forced strategy switch → %s (%s)",
                            decision.recommended_strategy,
                            decision.reason,
                        )

            # ── Beam management ───────────────────────────────────
            if self._iteration % self.config.beam.prune_interval == 0:
                scores = self.beam_mgr.score_beams()
                self.beam_mgr.prune()
                logger.info(
                    "Beam prune: %d active beams",
                    len(self.beam_mgr.beams),
                )

            # Sync the best beam back to the canonical state
            state = active_state

            self.logger.log_event("iteration_end", {
                "iteration": self._iteration,
                "verified": len(state.verified_claims),
                "open_subgoals": len(state.open_subgoals),
                "state_hash": state.state_hash(),
            })

        # ── Generate artifacts (Section 17) ───────────────────────
        artifacts = self._generate_artifacts(state, spec)

        self.logger.log_event("pipeline_end", {
            "iterations": self._iteration,
            "wall_time": time.time() - self._start_time,
            "verified_claims": len(state.verified_claims),
            "theorem_verified": state.has_verified_theorem(),
        })

        return artifacts

    # ═════════════════════════════════════════════════════════════
    # Single Iteration
    # ═════════════════════════════════════════════════════════════

    def _run_iteration(
        self,
        state: ProofState,
        spec: FormalSpec,
        dag: Any,
        *,
        predicate: Callable[..., bool] | None = None,
        domain: dict[str, Any] | None = None,
        z3_encoding: str = "",
        tptp_problem: str = "",
    ) -> bool:
        """
        Execute a single iteration of the proof loop.

        Returns True if progress was made.
        """
        made_progress = False

        # ── Identify frontier subgoals ────────────────────────────
        resolved = {
            sg.id for sg in state.subgoals.values() if sg.resolved
        }
        frontier = dag.frontier(resolved)

        if not frontier:
            logger.info("No frontier subgoals — replanning")
            dag = self.planner.replan(spec, state)
            for sg in dag.topological_order():
                if sg.id not in state.subgoals:
                    state.add_subgoal(sg)
            frontier = dag.frontier(resolved)

        if not frontier:
            logger.warning("No actionable subgoals after replanning")
            return False

        # ── Pick the highest-priority subgoal ─────────────────────
        target = frontier[0]
        logger.info(
            "Iteration %d: targeting subgoal %s (priority=%.2f)",
            self._iteration,
            target.id,
            target.effective_priority,
        )

        # ── Determine active strategies ───────────────────────────
        decision = self.strategy_ctrl.evaluate(
            state,
            last_strategy=self.strategy_ctrl.current_strategy,
        )
        if decision.should_switch:
            self.strategy_ctrl.current_strategy = (
                decision.recommended_strategy
            )
            logger.info(
                "Strategy switch → %s (%s)",
                decision.recommended_strategy,
                decision.reason,
            )
            # Update ensemble weights
            self.ensemble.update_weights(decision.weights)

        active_strategies = self.ensemble.get_active_proposers()

        # ── Proposer Ensemble (Section 6) ─────────────────────────
        candidates = self.ensemble.propose(
            target, spec, state, active_strategies=active_strategies
        )

        if not candidates:
            logger.warning(
                "No candidates produced for subgoal %s", target.id
            )
            return False

        # ── Rubric Agent: Pre-verification filter (Section 15A) ───
        filtered = self.rubric.filter_candidates(
            candidates, state, spec
        )

        if not filtered:
            logger.warning(
                "All %d candidates rejected by rubric", len(candidates)
            )
            # Postmortem on failures
            for cand in candidates:
                self.rubric.postmortem(
                    cand, verified=False, failed_stage="rubric"
                )
            return False

        logger.info(
            "%d/%d candidates passed rubric",
            len(filtered),
            len(candidates),
        )

        # ── Verification Cascade + Two-Phase Commit ───────────────
        for candidate in filtered:
            if self._time_exceeded():
                logger.warning("Wall time limit exceeded")
                break

            result = self._verify_and_commit(
                candidate,
                state,
                spec,
                predicate=predicate,
                domain=domain,
                z3_encoding=z3_encoding,
                tptp_problem=tptp_problem,
            )

            if result:
                made_progress = True
                # One verified claim per iteration is sufficient progress
                break

        return made_progress

    # ═════════════════════════════════════════════════════════════
    # Verification + Commit
    # ═════════════════════════════════════════════════════════════

    def _verify_and_commit(
        self,
        candidate: StepCandidate,
        state: ProofState,
        spec: FormalSpec,
        *,
        predicate: Callable[..., bool] | None = None,
        domain: dict[str, Any] | None = None,
        z3_encoding: str = "",
        tptp_problem: str = "",
    ) -> bool:
        """
        Run the verification cascade and two-phase commit.

        Returns True if the claim was verified.
        """
        # Create claim from candidate
        claim = Claim(
            statement=candidate.new_claims[0] if candidate.new_claims else "",
            claim_type=(
                ClaimType.THEOREM
                if "theorem" in candidate.action_type.lower()
                else ClaimType.LEMMA
            ),
            dependencies=candidate.dependencies,
            lean_code=candidate.lean_stub,
            strategy_family=candidate.strategy_family,
        )
        state.add_claim(claim)

        # ── Run cascade (Section 8) ───────────────────────────────
        cascade_result = self.cascade.verify(
            candidate,
            claim,
            spec,
            state,
            predicate=predicate,
            domain=domain,
            z3_encoding=z3_encoding,
            tptp_problem=tptp_problem,
        )

        self.logger.log_event("verification_result", {
            "claim_id": claim.id,
            "passed": cascade_result.passed,
            "failed_stage": cascade_result.failed_stage,
            "artifacts": len(cascade_result.artifacts),
        })

        # ── Lean Gate: Lemma minimization on V5 failure ──────────
        if (
            not cascade_result.passed
            and cascade_result.failed_stage == "V5"
            and candidate.lean_stub
        ):
            logger.info(
                "V5 failed for %s — attempting minimization", claim.id
            )
            min_result = self.minimizer.minimize(
                candidate.lean_stub,
                lean_errors=[cascade_result.details],
            )
            if min_result.success and min_result.minimized_lemmas:
                logger.info(
                    "Minimization produced %d sub-lemmas",
                    len(min_result.minimized_lemmas),
                )
                # TODO: Re-verify minimized lemmas in a follow-up iteration

        # ── Two-Phase Commit (Section 9) ──────────────────────────
        record = self.committer.commit(
            candidate, claim, cascade_result, state
        )

        # ── Rubric Agent: Postmortem (Section 15A) ────────────────
        policy_update = self.rubric.postmortem(
            candidate,
            verified=cascade_result.passed,
            failed_stage=cascade_result.failed_stage,
            state=state,
        )

        # Apply policy updates to the ensemble
        if policy_update.strategy_weight_deltas:
            self.ensemble.update_weights(
                policy_update.strategy_weight_deltas
            )

        # ── Counterexample-guided refinement (Section 12) ─────────
        if (
            not cascade_result.passed
            and cascade_result.counterexample is not None
        ):
            refinement = self.refiner.refine(
                claim.statement,
                cascade_result.counterexample,
                state,
            )
            if refinement.success:
                logger.info(
                    "Refinement produced: %s",
                    refinement.refined_claim[:80],
                )

        return cascade_result.passed

    # ═════════════════════════════════════════════════════════════
    # Pipeline Stages
    # ═════════════════════════════════════════════════════════════

    def _normalize(
        self, problem_id: str, raw_statement: str
    ) -> FormalSpec:
        """Normalize the problem statement (Section 4)."""
        spec = self.normalizer.normalize(
            problem_id,
            raw_statement,
            llm_assist=self.llm_assist,
        )
        self.logger.log_event("normalization_complete", {
            "problem_id": problem_id,
            "variables": len(spec.variables),
            "constraints": len(spec.constraints),
            "hash": spec.hash,
        })
        return spec

    def _generate_artifacts(
        self,
        state: ProofState,
        spec: FormalSpec,
    ) -> dict[str, Path]:
        """Generate all output artifacts (Section 17)."""
        return self.artifact_gen.generate_all(
            state,
            spec,
            config_dict=self._serialize_config(),
            pipeline_events=self._events,
        )

    # ═════════════════════════════════════════════════════════════
    # Termination (Section 19)
    # ═════════════════════════════════════════════════════════════

    def _should_terminate(self, state: ProofState) -> bool:
        """
        Check termination conditions (Section 19).

        Allowed only when:
        1. Target theorem verified (Lean success), OR
        2. Max iterations reached, OR
        3. Wall time exceeded.
        """
        # Condition 1: Theorem verified
        if state.has_verified_theorem():
            logger.info("TERMINATION: Theorem verified ✓")
            return True

        # Condition 2: Max iterations
        if self._iteration >= self.config.max_iterations:
            logger.warning(
                "TERMINATION: Max iterations (%d) reached",
                self.config.max_iterations,
            )
            return True

        # Condition 3: Wall time
        if self._time_exceeded():
            logger.warning("TERMINATION: Wall time limit exceeded")
            return True

        return False

    def _time_exceeded(self) -> bool:
        """Check if wall time limit has been exceeded."""
        elapsed = time.time() - self._start_time
        return elapsed > self.config.max_wall_time_seconds

    # ═════════════════════════════════════════════════════════════
    # Utilities
    # ═════════════════════════════════════════════════════════════

    def _serialize_config(self) -> dict[str, Any]:
        """Serialize config to dict for logging and artifacts."""
        return json.loads(
            json.dumps(dataclasses.asdict(self.config), default=str)
        )


# ═════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═════════════════════════════════════════════════════════════════

def main() -> None:
    """CLI entry point for running the pipeline."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="ampp",
        description="Autonomous Mathematical Proof Pipeline",
    )
    parser.add_argument(
        "problem",
        help="Mathematical problem statement (inline or file path)",
    )
    parser.add_argument(
        "--problem-id",
        default="problem_001",
        help="Unique problem identifier",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for output artifacts",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=200,
        help="Maximum number of iterations",
    )
    parser.add_argument(
        "--max-time",
        type=float,
        default=3600.0,
        help="Maximum wall time in seconds",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--lean-project",
        default="",
        help="Path to Lean project directory",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Read problem from file if it looks like a path
    problem_text = args.problem
    problem_path = Path(problem_text)
    if problem_path.exists() and problem_path.is_file():
        problem_text = problem_path.read_text().strip()

    # Build config
    from ampp.config import VerifierConfig

    config = PipelineConfig(
        output_dir=args.output_dir,
        max_iterations=args.max_iterations,
        max_wall_time_seconds=args.max_time,
        global_seed=args.seed,
        verifier=VerifierConfig(
            lean_project_dir=args.lean_project,
        ),
    )

    # Run
    pipeline = Pipeline(config)
    artifacts = pipeline.run(args.problem_id, problem_text)

    print(f"\n{'='*60}")
    print("AMPP Pipeline Complete")
    print(f"{'='*60}")
    for name, path in artifacts.items():
        print(f"  {name}: {path}")
    print()


if __name__ == "__main__":
    main()
