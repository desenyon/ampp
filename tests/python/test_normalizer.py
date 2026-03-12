"""Tests for the formal Normalizer."""
from __future__ import annotations


from ampp.normalizer import Normalizer
from ampp.schemas import FormalSpec


class TestNormalizer:
    def setup_method(self):
        self.norm = Normalizer()

    def test_basic_normalisation(self):
        spec = self.norm.normalize("For all n in N, n >= 0")
        assert isinstance(spec, FormalSpec)
        assert spec.raw_statement == "For all n in N, n >= 0"
        assert spec.target  # non-empty

    def test_latex_replacement(self):
        spec = self.norm.normalize("\\forall n \\in \\mathbb{N}, n \\geq 0")
        assert "for all" in spec.canonical_statement.lower()
        assert "N" in spec.canonical_statement

    def test_variable_extraction(self):
        spec = self.norm.normalize("For all n in N, n >= 1")
        assert "n" in spec.variables

    def test_edge_cases_generated(self):
        spec = self.norm.normalize("For all n in N, n(n+1) is even")
        assert len(spec.edge_cases) >= 1

    def test_lean_namespace_derived(self):
        spec = self.norm.normalize("For all primes p, p is odd or p equals 2")
        assert spec.lean_namespace  # non-empty valid identifier
        assert spec.lean_namespace[0].isupper()

    def test_fingerprint_stable(self):
        spec1 = self.norm.normalize("test statement")
        spec2 = self.norm.normalize("test statement")
        assert spec1.fingerprint() == spec2.fingerprint()

    def test_different_statements_different_fingerprints(self):
        s1 = self.norm.normalize("statement one")
        s2 = self.norm.normalize("statement two")
        assert s1.fingerprint() != s2.fingerprint()

    def test_quantifier_extraction(self):
        spec = self.norm.normalize("For all n in N there exists m such that m > n")
        assert any(q["quantifier"] == "for_all" for q in spec.quantifiers)
        assert any(q["quantifier"] == "exists" for q in spec.quantifiers)

    def test_constraint_extraction(self):
        spec = self.norm.normalize("For all n >= 2 in N, n has a prime factor")
        assert any("n" in c for c in spec.constraints)

    def test_empty_string_handled(self):
        spec = self.norm.normalize("")
        assert spec.raw_statement == ""
        assert spec.canonical_statement == ""
