"""Formal Normaliser — converts a raw problem statement into a FormalSpec.

All informal ambiguity is resolved here.  Downstream components receive
only the canonical, structured representation.

Two-pass strategy
─────────────────
1. Regex heuristics (fast, always runs).
2. LLM-assisted extraction (runs when a provider is configured) — enriches
   the spec with more accurate variables, domains, constraints, and edge cases.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from ampp.schemas import FormalSpec

logger = logging.getLogger(__name__)

_LLM_SYSTEM = (
    "You are a formal mathematics pre-processor.  Given a mathematical problem "
    "statement, extract a structured JSON representation.  Respond with ONLY a "
    "JSON object — no prose, no markdown fences.\n\n"
    "Required fields:\n"
    "  variables      : object mapping variable name → domain (e.g. {'n': 'N', 'x': 'R'})\n"
    "  quantifiers    : list of {quantifier, variable, domain}\n"
    "  constraints    : list of inequality/equality strings (e.g. ['n >= 1'])\n"
    "  target         : the precise statement to prove (one string)\n"
    "  edge_cases     : list of boundary-value strings (e.g. ['n=0', 'n=1'])\n"
    "  lean_namespace : a valid Lean 4 namespace identifier (CamelCase, ≤ 30 chars)\n"
)


class Normalizer:
    """Converts natural-language / LaTeX problem statements into FormalSpec objects."""

    def normalize(self, raw_statement: str) -> FormalSpec:
        """Parse and canonicalise the problem statement."""
        canonical = self._canonicalize(raw_statement)

        # -- Pass 1: regex heuristics -----------------------------------------
        variables = self._extract_variables(canonical)
        quantifiers = self._extract_quantifiers(canonical)
        constraints = self._extract_constraints(canonical)
        target = canonical
        edge_cases = self._infer_edge_cases(variables)
        lean_namespace = self._make_lean_namespace(canonical)

        # -- Pass 2: LLM enrichment (best-effort, non-critical) ---------------
        llm_data = self._llm_extract(raw_statement)
        if llm_data:
            variables = llm_data.get("variables", variables) or variables
            quantifiers = llm_data.get("quantifiers", quantifiers) or quantifiers
            constraints = llm_data.get("constraints", constraints) or constraints
            target = llm_data.get("target", target) or target
            edge_cases = llm_data.get("edge_cases", edge_cases) or edge_cases
            lean_ns = llm_data.get("lean_namespace", "")
            if lean_ns and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,29}", lean_ns):
                lean_namespace = lean_ns

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
        replacements = {
            r"\forall": "for all",
            r"\exists": "there exists",
            r"\in": "in",
            r"\leq": "<=",
            r"\geq": ">=",
            r"\neq": "!=",
            r"\cdot": "*",
            r"\binom": "C",
            r"\mathbb{N}": "N",
            r"\mathbb{Z}": "Z",
            r"\mathbb{R}": "R",
            r"\mathbb{Q}": "Q",
            r"\mid": "|",
            r"\nmid": "does not divide",
            r"\to": "->",
            r"\Rightarrow": "=>",
            r"\iff": "<=>",
            r"\infty": "infinity",
            r"\sum": "sum",
            r"\prod": "product",
        }
        for latex, plain in replacements.items():
            text = text.replace(latex, plain)
        text = re.sub(r"\s+", " ", text)
        return text

    def _extract_variables(self, text: str) -> dict[str, str]:
        vars_: dict[str, str] = {}
        for match in re.finditer(r"\b([a-zA-Z])\s+in\s+([A-Z])\b", text):
            vars_[match.group(1)] = match.group(2)
        for match in re.finditer(r"\bfor all\s+([a-zA-Z])\b", text):
            if match.group(1) not in vars_:
                vars_[match.group(1)] = "N"
        return vars_

    def _extract_quantifiers(self, text: str) -> list[dict[str, Any]]:
        qs: list[dict[str, Any]] = []
        if "for all" in text.lower():
            qs.append({"quantifier": "for_all", "variable": "n", "domain": "N"})
        if "there exists" in text.lower():
            qs.append({"quantifier": "exists", "variable": "x", "domain": "N"})
        return qs

    def _extract_constraints(self, text: str) -> list[str]:
        constraints = []
        for match in re.finditer(r"[a-zA-Z]\s*[><=!]+\s*\d+", text):
            constraints.append(match.group(0).strip())
        return list(dict.fromkeys(constraints))  # deduplicate, preserve order

    def _infer_edge_cases(self, variables: dict[str, str]) -> list[str]:
        cases = []
        for var, domain in variables.items():
            if domain in ("N", "Z"):
                cases.extend([f"{var}=0", f"{var}=1"])
        return cases

    def _make_lean_namespace(self, text: str) -> str:
        words = re.findall(r"[A-Za-z]+", text)[:4]
        return "".join(w.capitalize() for w in words) or "AMPP"

    def _llm_extract(self, raw: str) -> dict[str, Any] | None:
        """Call the LLM to extract structured fields.  Returns None on any failure."""
        try:
            from ampp.llm import get_provider, NullProvider
            provider = get_provider()
            if isinstance(provider, NullProvider):
                return None
            return provider.complete_json(_LLM_SYSTEM, raw)
        except Exception as exc:
            logger.debug("LLM normalisation failed (non-critical): %s", exc)
            return None
