"""Tests for ProposerEnsemble and strategy controller."""
from __future__ import annotations

import pytest

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
