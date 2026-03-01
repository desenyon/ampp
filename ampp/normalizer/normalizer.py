"""
Formal Normalization Layer (Section 4)

Converts a raw problem statement into a structured FormalSpec.
All notation is canonicalized before any reasoning occurs.
No informal ambiguity is allowed beyond this stage.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from ampp.models.state import FormalSpec, VariableDecl, _hash_str

logger = logging.getLogger(__name__)


class Normalizer:
    """
    Transforms a raw mathematical problem statement into a FormalSpec.

    The normalizer:
    1. Extracts variable declarations and domains
    2. Identifies quantifiers
    3. Extracts constraints
    4. Produces a canonical target statement
    5. Identifies edge cases
    """

    # Common mathematical domain patterns
    DOMAIN_PATTERNS: dict[str, str] = {
        r"\bnatural\b|\bpositive\s+integer": "ℕ",
        r"\binteger": "ℤ",
        r"\breal": "ℝ",
        r"\brational": "ℚ",
        r"\bfinite\s+set": "Finset",
        r"\bset\b": "Set",
        r"\bgraph\b": "SimpleGraph",
        r"\bsequence\b": "ℕ → ",
    }

    # Quantifier extraction patterns
    QUANTIFIER_PATTERNS: list[str] = [
        r"for\s+all",
        r"for\s+every",
        r"for\s+each",
        r"for\s+any",
        r"there\s+exists?",
        r"∀",
        r"∃",
    ]

    def normalize(
        self,
        problem_id: str,
        raw_statement: str,
        *,
        llm_assist: Any | None = None,
    ) -> FormalSpec:
        """
        Normalize a raw problem statement into a FormalSpec.

        Args:
            problem_id: Unique identifier for the problem.
            raw_statement: The raw mathematical problem text.
            llm_assist: Optional LLM callable for structured extraction.

        Returns:
            A fully populated FormalSpec.
        """
        logger.info("Normalizing problem %s", problem_id)

        if llm_assist is not None:
            return self._llm_normalize(problem_id, raw_statement, llm_assist)

        # Heuristic extraction (rule-based fallback)
        variables = self._extract_variables(raw_statement)
        quantifiers = self._extract_quantifiers(raw_statement)
        constraints = self._extract_constraints(raw_statement)
        target = self._extract_target(raw_statement)
        canonical = self._canonicalize(raw_statement, variables, target)
        edge_cases = self._identify_edge_cases(variables, constraints)

        spec = FormalSpec(
            problem_id=problem_id,
            raw_statement=raw_statement,
            variables=tuple(variables),
            quantifiers=tuple(quantifiers),
            constraints=tuple(constraints),
            target_statement=target,
            canonical_form=canonical,
            edge_cases=tuple(edge_cases),
        )

        logger.info(
            "Normalization complete: %d vars, %d constraints",
            len(variables),
            len(constraints),
        )
        return spec

    def _llm_normalize(
        self,
        problem_id: str,
        raw_statement: str,
        llm_assist: Any,
    ) -> FormalSpec:
        """Use an LLM to produce a structured normalization."""
        prompt = (
            "You are a mathematical formal specification builder. "
            "Given the following problem statement, extract:\n"
            "1. All variable declarations with their domains\n"
            "2. All quantifiers\n"
            "3. All constraints\n"
            "4. The target statement to prove\n"
            "5. A canonical mathematical form\n"
            "6. Edge cases\n\n"
            "Return a JSON object with keys: variables (list of "
            "{name, domain, constraints}), quantifiers (list of strings), "
            "constraints (list of strings), target_statement (string), "
            "canonical_form (string), edge_cases (list of strings).\n\n"
            f"Problem:\n{raw_statement}"
        )

        response = llm_assist(prompt)

        # Parse LLM response — expect JSON
        import json

        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            # Fallback to heuristic if LLM response is malformed
            logger.warning(
                "LLM normalization failed, falling back to heuristic"
            )
            return self.normalize(problem_id, raw_statement)

        variables = [
            VariableDecl(
                name=v.get("name", ""),
                domain=v.get("domain", ""),
                constraints=tuple(v.get("constraints", [])),
            )
            for v in data.get("variables", [])
        ]

        canonical = data.get("canonical_form", raw_statement)

        return FormalSpec(
            problem_id=problem_id,
            raw_statement=raw_statement,
            variables=tuple(variables),
            quantifiers=tuple(data.get("quantifiers", [])),
            constraints=tuple(data.get("constraints", [])),
            target_statement=data.get("target_statement", raw_statement),
            canonical_form=canonical,
            edge_cases=tuple(data.get("edge_cases", [])),
        )

    def _extract_variables(self, text: str) -> list[VariableDecl]:
        """Heuristic variable extraction from problem text."""
        variables: list[VariableDecl] = []
        # Look for patterns like "let n be a positive integer"
        let_pattern = re.compile(
            r"[Ll]et\s+([a-zA-Z_]\w*)\s+be\s+(?:a\s+)?(.+?)(?:\.|,|;|\band\b)",
            re.IGNORECASE,
        )
        for match in let_pattern.finditer(text):
            name = match.group(1)
            domain_text = match.group(2).strip()
            domain = self._classify_domain(domain_text)
            variables.append(VariableDecl(name=name, domain=domain))

        # Look for single-letter variables with domain hints
        for domain_pat, domain_sym in self.DOMAIN_PATTERNS.items():
            if re.search(domain_pat, text, re.IGNORECASE):
                # Extract candidate variable names near domain mentions
                region = text
                single_vars = re.findall(
                    r"\b([a-zA-Z])\b(?:\s*[,\s]\s*([a-zA-Z])\b)*",
                    region,
                )
                for group in single_vars:
                    for v in group:
                        if v and v not in [vd.name for vd in variables]:
                            # Only add if contextually relevant
                            pass

        if not variables:
            # Minimal fallback: find "for all X" or "let X"
            for_all = re.findall(
                r"(?:for\s+(?:all|every|each|any)\s+)([a-zA-Z_]\w*)",
                text,
                re.IGNORECASE,
            )
            for name in for_all:
                variables.append(VariableDecl(name=name, domain="unknown"))

        return variables

    def _classify_domain(self, text: str) -> str:
        """Classify a textual domain description to a canonical domain."""
        for pattern, domain in self.DOMAIN_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return domain
        return text

    def _extract_quantifiers(self, text: str) -> list[str]:
        """Extract quantifier phrases from text."""
        quantifiers: list[str] = []
        for pat in self.QUANTIFIER_PATTERNS:
            matches = re.finditer(
                rf"({pat}\s+[a-zA-Z_]\w*(?:\s*[,]\s*[a-zA-Z_]\w*)*)",
                text,
                re.IGNORECASE,
            )
            for m in matches:
                quantifiers.append(m.group(1).strip())
        return quantifiers

    def _extract_constraints(self, text: str) -> list[str]:
        """Extract constraints — inequalities, divisibility, etc."""
        constraints: list[str] = []
        # Various constraint patterns
        patterns = [
            r"(\w+\s*[<>≤≥=≠]+\s*\w+)",
            r"(\w+\s+divides?\s+\w+)",
            r"(\w+\s+is\s+(?:not\s+)?(?:prime|even|odd|positive|negative|zero))",
            r"(gcd\([^)]+\)\s*=\s*\d+)",
            r"(\w+\s*\|\s*\w+)",
        ]
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                constraints.append(m.group(1).strip())
        return constraints

    def _extract_target(self, text: str) -> str:
        """Extract the target statement (what to prove/show)."""
        # Look for "prove that", "show that", "find"
        patterns = [
            r"[Pp]rove\s+that\s+(.+?)(?:\.|$)",
            r"[Ss]how\s+that\s+(.+?)(?:\.|$)",
            r"[Ff]ind\s+(.+?)(?:\.|$)",
            r"[Dd]etermine\s+(.+?)(?:\.|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.DOTALL)
            if m:
                return m.group(1).strip()
        # Fallback: the entire statement is the target
        return text.strip()

    def _canonicalize(
        self,
        text: str,
        variables: list[VariableDecl],
        target: str,
    ) -> str:
        """Produce a canonical mathematical form."""
        parts: list[str] = []
        for v in variables:
            parts.append(f"{v.name} : {v.domain}")
        if parts:
            prefix = "∀ " + ", ".join(parts) + ", "
        else:
            prefix = ""
        return prefix + target

    def _identify_edge_cases(
        self,
        variables: list[VariableDecl],
        constraints: list[str],
    ) -> list[str]:
        """Identify potential edge cases."""
        edge_cases: list[str] = []
        for v in variables:
            if v.domain in ("ℕ", "ℤ"):
                edge_cases.append(f"{v.name} = 0")
                edge_cases.append(f"{v.name} = 1")
            elif v.domain in ("ℝ", "ℚ"):
                edge_cases.append(f"{v.name} = 0")
        return edge_cases
