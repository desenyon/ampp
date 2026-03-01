"""
Base Proposer (Section 6)

Abstract base class for all specialized proposers.
Each proposer outputs structured StepCandidate objects only.
No prose is accepted.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

from ampp.models.proof_state import ProofState
from ampp.models.state import FormalSpec, Subgoal
from ampp.models.step_candidate import StepCandidate

logger = logging.getLogger(__name__)


class BaseProposer(abc.ABC):
    """
    Abstract base for specialized proof-step proposers.

    Each concrete proposer specializes in a particular proof strategy
    (induction, extremal principle, double counting, etc.) and emits
    StepCandidate objects that conform to the schema.
    """

    name: str = "base"
    strategy_family: str = ""

    def __init__(self, llm_assist: Any | None = None) -> None:
        self.llm_assist = llm_assist

    @abc.abstractmethod
    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        """
        Generate StepCandidate objects for the given subgoal.

        Args:
            subgoal: The subgoal to address.
            spec: The formal specification.
            state: Current proof state.

        Returns:
            List of structurally complete StepCandidate objects.
            Incomplete candidates are filtered out.
        """
        ...

    def _filter_complete(
        self, candidates: list[StepCandidate]
    ) -> list[StepCandidate]:
        """Discard candidates missing required fields."""
        valid = []
        for c in candidates:
            if c.is_structurally_complete():
                valid.append(c)
            else:
                logger.debug(
                    "Proposer %s: discarding incomplete candidate %s",
                    self.name,
                    c.id,
                )
        return valid

    def _build_prompt(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> str:
        """Build a structured prompt for LLM-assisted proposal generation."""
        verified = [c.statement for c in state.verified_claims]
        rejected_hashes = state.claim_hashes()

        return (
            f"You are a {self.name} proof strategist.\n\n"
            f"Strategy family: {self.strategy_family}\n\n"
            f"Problem (canonical):\n{spec.canonical_form}\n\n"
            f"Current subgoal:\n{subgoal.statement}\n\n"
            f"Verified claims:\n{verified}\n\n"
            f"Rejected claim hashes (avoid): {len(rejected_hashes)} entries\n\n"
            "Generate a proof step as JSON with:\n"
            "- action_type: one of [introduce_definition, propose_lemma, "
            "apply_lemma, case_split, induction_step, rewrite, "
            "construct_witness, bound_argument]\n"
            "- new_claims: list of precise mathematical statements\n"
            "- dependencies: list of claim IDs this step depends on\n"
            "- verification_plan: {applicable_verifiers, success_criteria, "
            "z3_encoding_hint, lean_proof_sketch, falsification_bounds}\n"
            "- small_case_tests: list of {parameters, expected_result, "
            "description}\n"
            "- lean_stub: Lean 4 code skeleton\n"
            "- rationale: brief justification\n\n"
            "Return JSON array of step candidates."
        )

    def _parse_llm_candidates(
        self,
        response: str,
        subgoal: Subgoal,
    ) -> list[StepCandidate]:
        """Parse LLM response into StepCandidate objects."""
        import json

        from ampp.models.step_candidate import (
            SmallCaseTest,
            VerificationPlan,
        )

        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse LLM response for %s", self.name)
            return []

        if isinstance(data, dict):
            data = [data]

        candidates: list[StepCandidate] = []
        for item in data:
            vp_data = item.get("verification_plan", {})
            vp = VerificationPlan(
                applicable_verifiers=tuple(
                    vp_data.get("applicable_verifiers", [])
                ),
                success_criteria=vp_data.get("success_criteria", ""),
                z3_encoding_hint=vp_data.get("z3_encoding_hint", ""),
                lean_proof_sketch=vp_data.get("lean_proof_sketch", ""),
                falsification_bounds=vp_data.get("falsification_bounds", ""),
            )

            tests = []
            for t in item.get("small_case_tests", []):
                tests.append(
                    SmallCaseTest(
                        parameters=t.get("parameters", {}),
                        expected_result=t.get("expected_result"),
                        description=t.get("description", ""),
                    )
                )

            sc = StepCandidate(
                subgoal_id=subgoal.id,
                action_type=item.get("action_type", ""),
                new_claims=tuple(item.get("new_claims", [])),
                dependencies=tuple(item.get("dependencies", [])),
                verification_plan=vp,
                small_case_tests=tuple(tests),
                lean_stub=item.get("lean_stub", ""),
                strategy_family=self.strategy_family,
                rationale=item.get("rationale", ""),
                proposer_name=self.name,
            )
            candidates.append(sc)

        return self._filter_complete(candidates)
