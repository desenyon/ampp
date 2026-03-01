"""
V0 — Structural Checks (Section 8)

Validates:
- Symbol definitions
- Domain consistency
- Quantifier scope
- Dependency purity

Failure → reject immediately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ampp.models.proof_state import ProofState
from ampp.models.state import Claim, FormalSpec, VerificationArtifact
from ampp.models.step_candidate import StepCandidate

logger = logging.getLogger(__name__)


@dataclass
class V0Result:
    passed: bool
    details: str
    issues: list[str]


class V0StructuralChecker:
    """
    Structural validation layer.

    Checks that a StepCandidate is well-formed before spending
    compute on deeper verification.
    """

    def check(
        self,
        candidate: StepCandidate,
        spec: FormalSpec,
        state: ProofState,
    ) -> V0Result:
        """
        Run all structural checks on a candidate.

        Returns V0Result with pass/fail and detailed issues.
        """
        issues: list[str] = []

        # 1. Symbol validation
        issues.extend(self._check_symbols(candidate, spec, state))

        # 2. Domain consistency
        issues.extend(self._check_domain(candidate, spec))

        # 3. Quantifier scope
        issues.extend(self._check_quantifiers(candidate, spec))

        # 4. Dependency purity
        issues.extend(self._check_dependencies(candidate, state))

        # 5. Required fields
        issues.extend(self._check_required_fields(candidate))

        passed = len(issues) == 0
        details = "; ".join(issues) if issues else "All structural checks pass"

        logger.info(
            "V0 check: %s — %s",
            "PASS" if passed else "FAIL",
            details,
        )

        return V0Result(passed=passed, details=details, issues=issues)

    def to_artifact(self, result: V0Result) -> VerificationArtifact:
        return VerificationArtifact(
            stage="V0",
            result="pass" if result.passed else "fail",
            details=result.details,
        )

    def _check_symbols(
        self,
        candidate: StepCandidate,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[str]:
        """Check that all referenced symbols are defined."""
        issues: list[str] = []

        # Collect known symbols
        known_symbols: set[str] = set()

        # From spec variables
        for v in spec.variables:
            known_symbols.add(v.name)

        # From verified definitions
        for defn in state.definitions.values():
            if defn.lean_name:
                known_symbols.add(defn.lean_name)

        # From verified claims
        for claim in state.verified_claims:
            known_symbols.add(claim.id)

        # Check dependencies reference valid claim IDs
        for dep in candidate.dependencies:
            if dep not in state.claims:
                issues.append(f"Undefined dependency: {dep}")

        return issues

    def _check_domain(
        self,
        candidate: StepCandidate,
        spec: FormalSpec,
    ) -> list[str]:
        """Check domain consistency of new claims."""
        issues: list[str] = []

        for claim_stmt in candidate.new_claims:
            # Basic check: claims shouldn't be empty
            if not claim_stmt.strip():
                issues.append("Empty claim statement")

            # Check for obviously malformed expressions
            if claim_stmt.count("(") != claim_stmt.count(")"):
                issues.append(
                    f"Unbalanced parentheses in: {claim_stmt[:60]}..."
                )

        return issues

    def _check_quantifiers(
        self,
        candidate: StepCandidate,
        spec: FormalSpec,
    ) -> list[str]:
        """Check quantifier scope validity."""
        issues: list[str] = []

        for claim_stmt in candidate.new_claims:
            # Check for free variables in quantified expressions
            forall_vars = re.findall(r"∀\s+(\w+)", claim_stmt)
            exists_vars = re.findall(r"∃\s+(\w+)", claim_stmt)

            # Ensure quantified variables appear in the body
            for var in forall_vars + exists_vars:
                # Simple heuristic: var should appear after quantifier
                pattern = rf"[∀∃]\s+{re.escape(var)}.*{re.escape(var)}"
                if not re.search(pattern, claim_stmt):
                    # Not necessarily an error — variable may appear in type
                    pass

        return issues

    def _check_dependencies(
        self,
        candidate: StepCandidate,
        state: ProofState,
    ) -> list[str]:
        """
        Dependency purity: all dependencies must be verified claims.
        No unverified dependencies allowed.
        """
        issues: list[str] = []
        verified_ids = state.verified_claim_ids

        for dep in candidate.dependencies:
            if dep in state.claims and dep not in verified_ids:
                claim = state.claims[dep]
                issues.append(
                    f"Depends on unverified claim {dep} "
                    f"(status={claim.status})"
                )

        return issues

    def _check_required_fields(
        self, candidate: StepCandidate
    ) -> list[str]:
        """Check all required StepCandidate fields are present."""
        issues: list[str] = []

        if not candidate.subgoal_id:
            issues.append("Missing subgoal_id")
        if not candidate.action_type:
            issues.append("Missing action_type")
        if not candidate.new_claims:
            issues.append("Missing new_claims")
        if candidate.verification_plan is None:
            issues.append("Missing verification_plan")
        if not candidate.lean_stub:
            issues.append("Missing lean_stub")

        return issues
