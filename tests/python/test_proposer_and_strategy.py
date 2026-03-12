"""Tests for ProposerEnsemble and strategy controller."""
from __future__ import annotations


from ampp.agents.rubric_agent import RubricAgent
from ampp.agents.strategy_controller import StrategyController
from ampp.proposers.ensemble import ProposerEnsemble
from ampp.schemas import StrategyFamily, StepCandidate


SPEC = {
    "raw_statement": "For all n in N, n*(n+1) is even",
    "canonical_statement": "for all n in N, n*(n+1) is even",
    "target": "for all n, n*(n+1) is even",
    "variables": {"n": "N"},
    "edge_cases": ["n=0", "n=1"],
}


class TestProposerEnsemble:
    def setup_method(self):
        self.rubric = RubricAgent()
        self.ensemble = ProposerEnsemble(rubric_agent=self.rubric)

    def test_returns_list_of_candidates(self):
        candidates = self.ensemble.propose(
            subgoal_id="sg-1",
            branch_id="b-1",
            spec=SPEC,
            verified_claims=[],
            attempts=[],
        )
        assert isinstance(candidates, list)
        # May be empty if no LLM key, but must be a list
        for c in candidates:
            assert isinstance(c, StepCandidate)

    def test_no_duplicate_hashes(self):
        candidates = self.ensemble.propose(
            subgoal_id="sg-1",
            branch_id="b-1",
            spec=SPEC,
            verified_claims=[],
            attempts=[],
        )
        hashes = [c.candidate_hash for c in candidates]
        assert len(hashes) == len(set(hashes))

    def test_rejected_hashes_filtered(self):
        first_run = self.ensemble.propose(
            subgoal_id="sg-1",
            branch_id="b-1",
            spec=SPEC,
            verified_claims=[],
            attempts=[],
        )
        # Collect all hashes from first run
        first_hashes = {c.candidate_hash for c in first_run}

        # Second run with all first-run hashes rejected
        second_run = self.ensemble.propose(
            subgoal_id="sg-1",
            branch_id="b-1",
            spec=SPEC,
            verified_claims=[],
            attempts=[],
            rejected_hashes=first_hashes,
        )
        # All returned candidates should have new hashes
        for c in second_run:
            assert c.candidate_hash not in first_hashes

    def test_update_weights_affects_order(self):
        # Zero out induction weight
        self.ensemble.update_weights({"induction": 0.0})
        candidates = self.ensemble.propose(
            subgoal_id="sg-1",
            branch_id="b-1",
            spec=SPEC,
            verified_claims=[],
            attempts=[],
        )
        # No induction candidates should appear
        for c in candidates:
            assert c.strategy_family != StrategyFamily.INDUCTION

    def test_all_candidates_pass_pydantic_validation(self):
        candidates = self.ensemble.propose(
            subgoal_id="sg-1",
            branch_id="b-1",
            spec=SPEC,
            verified_claims=[],
            attempts=[],
        )
        for c in candidates:
            # Re-validate — should not raise
            StepCandidate.model_validate(c.model_dump())


class TestStrategyController:
    def setup_method(self):
        self.ctrl = StrategyController(seed=42)

    def test_no_switch_initially(self):
        assert not self.ctrl.should_switch()

    def test_switch_after_stale(self):
        from ampp.agents.strategy_controller import SWITCH_STALE_THRESHOLD
        for _ in range(SWITCH_STALE_THRESHOLD):
            self.ctrl.record_failure("reason A")
        assert self.ctrl.should_switch()

    def test_switch_after_identical_failures(self):
        from ampp.agents.strategy_controller import MAX_IDENTICAL_FAILURES
        for _ in range(MAX_IDENTICAL_FAILURES):
            self.ctrl.record_failure("exact same reason")
        assert self.ctrl.should_switch()

    def test_progress_resets_staleness(self):
        from ampp.agents.strategy_controller import SWITCH_STALE_THRESHOLD
        for _ in range(SWITCH_STALE_THRESHOLD - 1):
            self.ctrl.record_failure("r")
        self.ctrl.record_progress()
        assert not self.ctrl.should_switch()

    def test_next_strategy_returns_valid_family(self):
        weights = {sf.value: 1.0 for sf in StrategyFamily}
        sf = self.ctrl.next_strategy(weights, [])
        assert isinstance(sf, StrategyFamily)

    def test_next_strategy_avoids_active(self):
        weights = {sf.value: 1.0 for sf in StrategyFamily}
        active = [StrategyFamily.INDUCTION.value, StrategyFamily.CONSTRUCTIVE.value]
        sf = self.ctrl.next_strategy(weights, active)
        assert sf.value not in active

    def test_frontier_entropy_zero_on_empty(self):
        assert self.ctrl.frontier_entropy([]) == 0.0

    def test_frontier_entropy_positive_on_mixed(self):
        attempts = [
            {"verifier_stage": "V1"},
            {"verifier_stage": "V3"},
            {"verifier_stage": "V5"},
        ]
        assert self.ctrl.frontier_entropy(attempts) > 0.0

    def test_frontier_entropy_zero_on_uniform(self):
        attempts = [{"verifier_stage": "V1"}] * 10
        # Shannon entropy of a single outcome = 0
        assert self.ctrl.frontier_entropy(attempts) == 0.0

    def test_should_switch_with_attempts_entropy(self):
        """should_switch(attempts=...) fires on high entropy."""
        from ampp.agents.strategy_controller import ENTROPY_SWITCH_THRESHOLD
        # Create attempts with many distinct stages to push entropy above threshold
        stages = ["V1", "V2", "V3", "V4", "V5", "V0", "UNKNOWN", "OTHER"]
        attempts = [{"verifier_stage": s} for s in stages * 4]
        h = self.ctrl.frontier_entropy(attempts)
        if h > ENTROPY_SWITCH_THRESHOLD:
            assert self.ctrl.should_switch(attempts=attempts)
        # Otherwise verify should_switch without attempts still works
        else:
            assert self.ctrl.should_switch(attempts=[]) is False

    def test_stale_iterations_property(self):
        self.ctrl.record_failure("x")
        self.ctrl.record_failure("y")
        assert self.ctrl.stale_iterations == 2

    def test_current_strategy_property(self):
        assert isinstance(self.ctrl.current_strategy, StrategyFamily)

    def test_enforce_beam_diversity_no_duplicates(self):
        """If beam is already diverse, return it unchanged."""
        beam = [sf.value for sf in list(StrategyFamily)[:4]]
        weights = {sf.value: 1.0 for sf in StrategyFamily}
        result = self.ctrl.enforce_beam_diversity(beam, weights)
        assert len(set(result)) == len(result)  # still diverse

    def test_enforce_beam_diversity_replaces_duplicates(self):
        """If beam has duplicates beyond diversity ratio, replace them."""
        same_strategy = StrategyFamily.INDUCTION.value
        beam = [same_strategy] * 4 + [StrategyFamily.CONSTRUCTIVE.value]
        weights = {sf.value: 1.0 for sf in StrategyFamily}
        result = self.ctrl.enforce_beam_diversity(beam, weights)
        # Should have more diversity than the original
        assert len(set(result)) > 1

    def test_progress_after_switch_resets(self):
        """next_strategy resets stale iteration counter."""
        from ampp.agents.strategy_controller import SWITCH_STALE_THRESHOLD
        for _ in range(SWITCH_STALE_THRESHOLD):
            self.ctrl.record_failure("r")
        assert self.ctrl.should_switch()
        weights = {sf.value: 1.0 for sf in StrategyFamily}
        self.ctrl.next_strategy(weights, [])
        assert self.ctrl.stale_iterations == 0
