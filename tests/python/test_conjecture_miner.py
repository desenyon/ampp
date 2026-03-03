"""Conjecture miner tests."""
from ampp.agents.conjecture_miner import ConjectureMiner


class TestConjectureMiner:
    def setup_method(self):
        self.miner = ConjectureMiner(seed=42)

    def test_returns_list(self):
        conjectures = self.miner.mine({"target": "n*(n+1) is even"})
        assert isinstance(conjectures, list)

    def test_no_duplicates(self):
        conjectures = self.miner.mine({"target": "test"})
        assert len(conjectures) == len(set(conjectures))

    def test_non_empty_on_real_problem(self):
        conjectures = self.miner.mine(
            {"target": "For all n, there is a prime between n and 2n"}, bound=20
        )
        assert len(conjectures) > 0
