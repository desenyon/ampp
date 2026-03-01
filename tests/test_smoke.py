"""Basic smoke tests for AMPP imports and core functionality."""

from __future__ import annotations


def test_imports():
    """Verify all core modules import without error."""
    from ampp.config import (
        PipelineConfig,
        VerifierConfig,
        BeamConfig,
        StrategyConfig,
        RubricConfig,
        ClaimStatus,
        ClaimType,
        VerifierStage,
        ActionType,
        StrategyFamily,
    )
    assert StrategyFamily.INDUCTION == "induction"
    assert len(StrategyFamily.ALL) == 10


def test_state_models():
    """Test core state model creation."""
    from ampp.models.state import (
        VariableDecl,
        FormalSpec,
        Definition,
        Claim,
        Subgoal,
        Counterexample,
        Attempt,
        VerificationArtifact,
    )

    var = VariableDecl(name="n", domain="ℕ")
    assert var.name == "n"
    assert var.domain == "ℕ"

    claim = Claim(statement="∀ n, n + 0 = n")
    assert claim.status == "proposed"
    assert not claim.is_verified

    verified = claim.with_status("verified")
    assert verified.is_verified
    assert verified.statement == claim.statement

    sg = Subgoal(
        target_claim="c1",
        statement="Base case",
        priority_score=5.0,
        difficulty_estimate=2.0,
    )
    assert sg.effective_priority == 2.5


def test_proof_state():
    """Test ProofState append-only operations."""
    from ampp.models.proof_state import ProofState
    from ampp.models.state import Claim, Subgoal

    state = ProofState()
    assert state.version == 0

    c1 = Claim(id="c1", statement="claim 1")
    state.add_claim(c1)
    assert state.version == 1
    assert "c1" in state.claims

    state.verify_claim("c1")
    assert state.version == 2
    assert state.claims["c1"].is_verified
    assert len(state.verified_claims) == 1

    c2 = Claim(id="c2", statement="claim 2")
    state.add_claim(c2)
    state.reject_claim("c2", "counterexample found")
    assert state.claims["c2"].is_rejected
    assert len(state.rejected_claims) == 1


def test_step_candidate():
    """Test StepCandidate schema validation."""
    from ampp.models.step_candidate import (
        StepCandidate,
        VerificationPlan,
        SmallCaseTest,
    )

    # Incomplete candidate
    incomplete = StepCandidate(subgoal_id="sg1")
    assert not incomplete.is_structurally_complete()

    # Complete candidate
    complete = StepCandidate(
        subgoal_id="sg1",
        action_type="propose_lemma",
        new_claims=("∀ n, P(n)",),
        verification_plan=VerificationPlan(
            applicable_verifiers=("V0", "V1", "V5"),
        ),
        small_case_tests=(
            SmallCaseTest(parameters={"n": 1}, expected_result=True),
        ),
        lean_stub="theorem p : True := trivial",
    )
    assert complete.is_structurally_complete()


def test_formal_spec():
    """Test FormalSpec creation and hashing."""
    from ampp.models.state import FormalSpec, VariableDecl

    spec = FormalSpec(
        problem_id="test",
        raw_statement="For all n >= 1, prove P(n)",
        variables=(VariableDecl(name="n", domain="ℕ"),),
        quantifiers=("∀ n : ℕ",),
        constraints=("n ≥ 1",),
        target_statement="P(n)",
        canonical_form="∀ n ∈ ℕ, n ≥ 1 → P(n)",
    )
    assert spec.hash  # auto-computed
    assert spec.problem_id == "test"


def test_config_defaults():
    """Test config default values."""
    from ampp.config import PipelineConfig

    cfg = PipelineConfig()
    assert cfg.max_iterations == 200
    assert cfg.global_seed == 42
    assert cfg.verifier.max_exhaustive_n == 12
    assert cfg.beam.min_beams == 3
    assert cfg.rubric.pass_threshold == 0.4


def test_normalizer():
    """Test normalizer heuristic extraction."""
    from ampp.normalizer.normalizer import Normalizer

    n = Normalizer()
    spec = n.normalize(
        "test_gauss",
        "Prove that for all positive integers n, "
        "the sum 1 + 2 + ... + n equals n(n+1)/2.",
    )
    assert spec.problem_id == "test_gauss"
    assert spec.raw_statement
    assert spec.canonical_form


def test_proof_state_clone():
    """Test ProofState deep cloning for beam branching."""
    from ampp.models.proof_state import ProofState
    from ampp.models.state import Claim

    state = ProofState(branch_id="main")
    state.add_claim(Claim(id="c1", statement="test"))

    clone = state.clone("beam_1")
    assert clone.branch_id == "beam_1"
    assert "c1" in clone.claims
    assert clone.version == state.version

    # Mutations to clone don't affect original
    clone.add_claim(Claim(id="c2", statement="clone claim"))
    assert "c2" not in state.claims


def test_pipeline_init():
    """Test Pipeline initialization."""
    from ampp.main import Pipeline
    from ampp.config import PipelineConfig

    config = PipelineConfig(
        max_iterations=5,
        max_wall_time_seconds=10.0,
    )
    pipeline = Pipeline(config)
    assert pipeline.config.max_iterations == 5
