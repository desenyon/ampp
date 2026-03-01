"""
Counterexample-Guided Refinement (Section 12)

When a claim fails:
- Extract structural features of witness
- Generalize failure condition
- Add exclusion constraints
- Regenerate refined lemma

Prevents repeated failure patterns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ampp.models.proof_state import ProofState
from ampp.models.state import Counterexample

logger = logging.getLogger(__name__)


@dataclass
class RefinementResult:
    """Result of counterexample-guided refinement."""
    original_claim: str
    refined_claim: str
    exclusion_constraints: list[str]
    structural_features: dict[str, Any]
    success: bool
    details: str = ""


class CounterexampleRefiner:
    """
    Refines claims based on counterexample feedback.

    Analyzes the witness structure of a counterexample to:
    1. Extract patterns that cause failure
    2. Add constraints excluding those patterns
    3. Generate a refined, stronger claim
    """

    def __init__(self, llm_assist: Any | None = None) -> None:
        self.llm_assist = llm_assist

    def refine(
        self,
        claim_statement: str,
        counterexample: Counterexample,
        state: ProofState,
    ) -> RefinementResult:
        """
        Refine a claim based on a counterexample.

        Args:
            claim_statement: The original claim that was disproved.
            counterexample: The counterexample witness.
            state: Current proof state.

        Returns:
            RefinementResult with the refined claim.
        """
        logger.info(
            "Refining claim based on counterexample: %s",
            counterexample.witness_structure,
        )

        # 1. Extract structural features
        features = self._extract_features(counterexample)

        # 2. Generalize failure condition
        exclusions = self._generalize_failure(
            claim_statement, counterexample, features
        )

        # 3. Generate refined claim
        if self.llm_assist:
            refined = self._llm_refine(
                claim_statement, counterexample, features, exclusions
            )
        else:
            refined = self._heuristic_refine(
                claim_statement, exclusions
            )

        return RefinementResult(
            original_claim=claim_statement,
            refined_claim=refined,
            exclusion_constraints=exclusions,
            structural_features=features,
            success=bool(refined and refined != claim_statement),
        )

    def extract_failure_pattern(
        self,
        counterexamples: list[Counterexample],
    ) -> dict[str, Any]:
        """
        Extract common patterns from multiple counterexamples.

        Used to build global exclusion constraints.
        """
        if not counterexamples:
            return {}

        # Analyze common features across counterexamples
        all_features: list[dict[str, Any]] = []
        for cx in counterexamples:
            features = self._extract_features(cx)
            all_features.append(features)

        # Find common keys
        if not all_features:
            return {}

        common_keys = set(all_features[0].keys())
        for f in all_features[1:]:
            common_keys &= set(f.keys())

        # Extract patterns
        pattern: dict[str, Any] = {}
        for key in common_keys:
            values = [f[key] for f in all_features]
            if len(set(str(v) for v in values)) == 1:
                pattern[f"{key}_constant"] = values[0]
            else:
                pattern[f"{key}_range"] = {
                    "min": min(v for v in values if isinstance(v, (int, float))),
                    "max": max(v for v in values if isinstance(v, (int, float))),
                } if all(isinstance(v, (int, float)) for v in values) else {
                    "values": values
                }

        return pattern

    def _extract_features(
        self, counterexample: Counterexample
    ) -> dict[str, Any]:
        """Extract structural features from a counterexample witness."""
        witness = counterexample.witness_structure
        features: dict[str, Any] = {}

        for key, value in witness.items():
            features[key] = value

            # Numeric features
            if isinstance(value, (int, float)):
                features[f"{key}_parity"] = "even" if value % 2 == 0 else "odd"
                features[f"{key}_sign"] = (
                    "positive" if value > 0
                    else "negative" if value < 0
                    else "zero"
                )

            # Collection features
            elif isinstance(value, (list, tuple)):
                features[f"{key}_size"] = len(value)
                if all(isinstance(v, (int, float)) for v in value):
                    features[f"{key}_sum"] = sum(value)
                    features[f"{key}_sorted"] = value == sorted(value)

        features["generation_method"] = counterexample.generation_method
        return features

    def _generalize_failure(
        self,
        claim: str,
        counterexample: Counterexample,
        features: dict[str, Any],
    ) -> list[str]:
        """Generalize the failure condition into exclusion constraints."""
        exclusions: list[str] = []
        witness = counterexample.witness_structure

        for key, value in witness.items():
            if isinstance(value, (int, float)):
                # Exclude the specific value and nearby values
                exclusions.append(f"{key} ≠ {value}")

                # Add a constraint based on parity if relevant
                parity = features.get(f"{key}_parity")
                if parity:
                    exclusions.append(f"Consider: {key} is {parity}")

        return exclusions

    def _heuristic_refine(
        self,
        claim: str,
        exclusions: list[str],
    ) -> str:
        """Simple heuristic refinement: append constraints."""
        if not exclusions:
            return claim

        constraint_str = " ∧ ".join(exclusions[:3])  # Limit constraints
        return f"({claim}) with additional constraint: {constraint_str}"

    def _llm_refine(
        self,
        claim: str,
        counterexample: Counterexample,
        features: dict[str, Any],
        exclusions: list[str],
    ) -> str:
        """Use LLM to generate a refined claim."""
        import json

        prompt = (
            "A mathematical claim was disproved by a counterexample.\n\n"
            f"Original claim:\n{claim}\n\n"
            f"Counterexample:\n{json.dumps(counterexample.witness_structure)}\n\n"
            f"Structural features:\n{json.dumps(features)}\n\n"
            f"Suggested exclusions:\n{json.dumps(exclusions)}\n\n"
            "Generate a refined claim that:\n"
            "1. Excludes the counterexample pattern\n"
            "2. Is still meaningful and useful\n"
            "3. Is strictly stronger (more restrictive) than before\n\n"
            "Return only the refined claim statement as a string."
        )

        try:
            response = self.llm_assist(prompt)  # type: ignore[misc]
            return response.strip().strip('"')
        except Exception as e:
            logger.warning("LLM refinement failed: %s", e)
            return self._heuristic_refine(claim, exclusions)
