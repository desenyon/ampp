"""
StepCandidate schema — the universal unit of proposed proof progress.

Every proposer must emit StepCandidate objects. Any candidate missing
required fields is automatically discarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ampp.models.state import _new_id


@dataclass(frozen=True)
class SmallCaseTest:
    """A concrete test case for small parameter values."""
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_result: Any = None
    description: str = ""


@dataclass(frozen=True)
class VerificationPlan:
    """
    Concrete plan specifying how to verify the candidate's claims.
    Must be executable by the verifier stack.
    """
    applicable_verifiers: tuple[str, ...] = ()  # ("V1", "V2", "V3", "V5")
    success_criteria: str = ""
    z3_encoding_hint: str = ""
    lean_proof_sketch: str = ""
    falsification_bounds: str = ""  # e.g., "test all n <= 10"
    estimated_difficulty: float = 1.0


@dataclass(frozen=True)
class StepCandidate:
    """
    A structured proof step proposed by a proposer.

    Required fields (hard-gate — missing → discard):
        subgoal_id, action_type, new_claims, dependencies,
        verification_plan, small_case_tests, lean_stub

    The Rubric Agent scores and filters candidates before they enter
    the verification cascade.
    """
    id: str = field(default_factory=_new_id)
    subgoal_id: str = ""
    action_type: str = ""
    new_claims: tuple[str, ...] = ()           # claim statements
    dependencies: tuple[str, ...] = ()         # claim IDs required
    verification_plan: VerificationPlan | None = None
    small_case_tests: tuple[SmallCaseTest, ...] = ()
    lean_stub: str = ""

    # Metadata (optional but scored)
    strategy_family: str = ""
    rationale: str = ""
    complexity_reduction_estimate: float = 0.0
    proposer_name: str = ""

    # Rubric score (set by Rubric Agent)
    rubric_score: float = -1.0
    rubric_pass: bool = False
    rubric_notes: str = ""

    def is_structurally_complete(self) -> bool:
        """Check whether all required fields are populated."""
        return bool(
            self.subgoal_id
            and self.action_type
            and self.new_claims
            and self.verification_plan is not None
            and self.lean_stub
        )

    def with_rubric(
        self, score: float, passed: bool, notes: str = ""
    ) -> StepCandidate:
        """Return a copy with rubric results attached."""
        return StepCandidate(
            id=self.id,
            subgoal_id=self.subgoal_id,
            action_type=self.action_type,
            new_claims=self.new_claims,
            dependencies=self.dependencies,
            verification_plan=self.verification_plan,
            small_case_tests=self.small_case_tests,
            lean_stub=self.lean_stub,
            strategy_family=self.strategy_family,
            rationale=self.rationale,
            complexity_reduction_estimate=self.complexity_reduction_estimate,
            proposer_name=self.proposer_name,
            rubric_score=score,
            rubric_pass=passed,
            rubric_notes=notes,
        )
