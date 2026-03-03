"""Formal Normaliser — converts a raw problem statement into a FormalSpec.

All informal ambiguity is resolved here.  Downstream components receive
only the canonical, structured representation.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from ampp.schemas import FormalSpec

logger = logging.getLogger(__name__)


class Normalizer:
    """Converts natural-language problem statements into FormalSpec objects."""

    def normalize(self, raw_statement: str) -> FormalSpec:
        """Parse and canonicalise the problem statement."""
        canonical = self._canonicalize(raw_statement)
        variables = self._extract_variables(canonical)
        quantifiers = self._extract_quantifiers(canonical)
        constraints = self._extract_constraints(canonical)
        target = self._extract_target(canonical)
        edge_cases = self._infer_edge_cases(variables)
        lean_namespace = self._make_lean_namespace(canonical)

        return FormalSpec(
            raw_statement=raw_statement,
            canonical_statement=canonical,
            variables=variables,
            quantifiers=quantifiers,
            constraints=constraints,
            target=target,
            edge_cases=edge_cases,
            lean_namespace=lean_namespace,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _canonicalize(self, text: str) -> str:
        """Strip formatting, normalise Unicode and LaTeX."""
        text = text.strip()
        # Normalise common LaTeX to ASCII
        replacements = {
            "\\forall": "for all",
            "\\exists": "there exists",
            "\\in": "in",
            "\\leq": "<=",
            "\\geq": ">=",
            "\\neq": "!=",
            "\\cdot": "*",
            "\\binom": "C",
            "\\mathbb{N}": "N",
            "\\mathbb{Z}": "Z",
            "\\mathbb{R}": "R",
        }
        for latex, plain in replacements.items():
            text = text.replace(latex, plain)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text)
        return text

    def _extract_variables(self, text: str) -> dict[str, str]:
        """Heuristically extract variable names and their domains."""
        vars_: dict[str, str] = {}
        # Match patterns like "n in N", "x in R"
        for match in re.finditer(r"\b([a-zA-Z])\s+in\s+([A-Z])\b", text):
            vars_[match.group(1)] = match.group(2)
        # Match "for all n >= 1"
        for match in re.finditer(r"\bfor all\s+([a-zA-Z])\b", text):
            if match.group(1) not in vars_:
                vars_[match.group(1)] = "N"
        return vars_

    def _extract_quantifiers(self, text: str) -> list[dict[str, Any]]:
        qs = []
        if "for all" in text.lower():
            qs.append({"quantifier": "for_all", "variable": "n", "domain": "N"})
        if "there exists" in text.lower():
            qs.append({"quantifier": "exists", "variable": "x", "domain": "N"})
        return qs

    def _extract_constraints(self, text: str) -> list[str]:
        constraints = []
        # Match "n >= k" style
        for match in re.finditer(r"[a-zA-Z]\s*[><=!]+\s*\d+", text):
            constraints.append(match.group(0))
        return constraints

    def _extract_target(self, text: str) -> str:
        """The entire canonical statement is the target for now."""
        return text

    def _infer_edge_cases(self, variables: dict[str, str]) -> list[str]:
        cases = []
        for var, domain in variables.items():
            if domain in ("N", "Z"):
                cases.extend([f"{var}=0", f"{var}=1"])
        return cases

    def _make_lean_namespace(self, text: str) -> str:
        # Derive a safe Lean namespace identifier from the first few words
        words = re.findall(r"[A-Za-z]+", text)[:4]
        return "".join(w.capitalize() for w in words) or "AMPP"
