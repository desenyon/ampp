"""
Global configuration and constants for the AMPP pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VerifierConfig:
    """Configuration for the verification cascade."""

    # V1 — Counterexample search
    max_exhaustive_n: int = 12
    random_test_count: int = 5000
    boundary_test_count: int = 200
    counterexample_seed: int = 42

    # V2 — SymPy symbolic verification
    sympy_timeout_seconds: float = 30.0

    # V3 — Z3 SMT
    z3_timeout_ms: int = 30_000

    # V4 — ATP (Vampire / E)
    atp_timeout_seconds: float = 60.0
    atp_binary: str = "vampire"  # or "eprover"

    # V5 — Lean
    lean_project_dir: str = ""
    lean_timeout_seconds: float = 120.0
    lean_toolchain: str = "leanprover/lean4:v4.8.0"


@dataclass(frozen=True)
class BeamConfig:
    """Configuration for beam search."""

    min_beams: int = 3
    max_beams: int = 6
    diversity_threshold: float = 0.3
    prune_interval: int = 5


@dataclass(frozen=True)
class StrategyConfig:
    """Configuration for strategy switching."""

    stall_threshold: int = 5  # iterations without progress before switch
    entropy_threshold: float = 0.85
    initial_weights: dict[str, float] = field(default_factory=lambda: {
        "induction": 1.0,
        "strong_induction": 1.0,
        "extremal": 1.0,
        "invariant": 1.0,
        "counting": 1.0,
        "construction": 1.0,
        "contradiction": 1.0,
        "algebraic": 1.0,
        "graph_translation": 1.0,
        "minimal_counterexample": 1.0,
    })


@dataclass(frozen=True)
class RubricConfig:
    """Configuration for the rubric agent."""

    # Hard gate thresholds
    max_step_size: int = 5  # max new claims per step
    require_small_case_tests: bool = True

    # Scoring weights
    weight_checkability: float = 1.0
    weight_locality: float = 1.0
    weight_dependency_hygiene: float = 1.0
    weight_counterexample_risk: float = 1.0
    weight_complexity_reduction: float = 0.7
    weight_novelty: float = 0.5
    weight_lean_friendliness: float = 0.6

    # Pass threshold (scored dimensions only, after hard gates)
    pass_threshold: float = 0.4


@dataclass(frozen=True)
class PipelineConfig:
    """Top-level pipeline configuration."""

    # Directories
    workspace_dir: str = field(default_factory=lambda: os.getcwd())
    output_dir: str = "output"
    log_dir: str = "logs"

    # Iteration limits
    max_iterations: int = 200
    max_wall_time_seconds: float = 3600.0

    # Reproducibility
    global_seed: int = 42

    # Sub-configs
    verifier: VerifierConfig = field(default_factory=VerifierConfig)
    beam: BeamConfig = field(default_factory=BeamConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    rubric: RubricConfig = field(default_factory=RubricConfig)

    @property
    def output_path(self) -> Path:
        return Path(self.workspace_dir) / self.output_dir

    @property
    def log_path(self) -> Path:
        return Path(self.workspace_dir) / self.log_dir


# ── Enumerations ──────────────────────────────────────────────────────────

class ClaimStatus:
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ClaimType:
    LEMMA = "lemma"
    THEOREM = "theorem"
    AUXILIARY = "auxiliary"


class VerifierStage:
    V0_STRUCTURAL = "V0"
    V1_COUNTEREXAMPLE = "V1"
    V2_SYMBOLIC = "V2"
    V3_SMT = "V3"
    V4_ATP = "V4"
    V5_LEAN = "V5"


class ActionType:
    INTRODUCE_DEFINITION = "introduce_definition"
    PROPOSE_LEMMA = "propose_lemma"
    APPLY_LEMMA = "apply_lemma"
    CASE_SPLIT = "case_split"
    INDUCTION_STEP = "induction_step"
    REWRITE = "rewrite"
    CONSTRUCT_WITNESS = "construct_witness"
    BOUND_ARGUMENT = "bound_argument"


class StrategyFamily:
    INDUCTION = "induction"
    STRONG_INDUCTION = "strong_induction"
    EXTREMAL = "extremal"
    INVARIANT = "invariant"
    COUNTING = "counting"
    CONSTRUCTION = "construction"
    CONTRADICTION = "contradiction"
    ALGEBRAIC = "algebraic"
    GRAPH_TRANSLATION = "graph_translation"
    MINIMAL_COUNTEREXAMPLE = "minimal_counterexample"

    ALL = [
        "induction", "strong_induction", "extremal", "invariant",
        "counting", "construction", "contradiction", "algebraic",
        "graph_translation", "minimal_counterexample",
    ]
