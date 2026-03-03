"""Base interface for all Proposer specialisations."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any

import uuid

from ampp.schemas import (
    ActionType,
    NewClaimSpec,
    SmallCaseTest,
    StepCandidate,
    StrategyFamily,
    VerificationPlan,
)


class BaseProposer(ABC):
    """Abstract base class for a single-strategy proposer.

    Each proposer generates one or more StepCandidates for a given subgoal.
    All candidates must pass pydantic validation before being returned.
    """

    @property
    @abstractmethod
    def strategy_family(self) -> StrategyFamily:
        ...

    @abstractmethod
    def propose(
        self,
        subgoal_id: str,
        branch_id: str,
        spec: dict[str, Any],
        verified_claims: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
    ) -> list[StepCandidate]:
        """Generate candidate proof steps for the given subgoal."""
        ...

    # ── Utility helpers for subclasses ────────────────────────────────────────

    def _build_candidate(
        self,
        subgoal_id: str,
        branch_id: str,
        action_type: ActionType,
        statements: list[str],
        dependencies: list[str],
        stages: list[str],
        lean_stub: str,
        small_cases: list[SmallCaseTest] | None = None,
        success_criteria: dict[str, str] | None = None,
        enumeration_bound: int | None = None,
    ) -> StepCandidate:
        new_claims = [NewClaimSpec(statement=s) for s in statements]
        candidate_hash = self._hash_candidate(subgoal_id, statements)
        return StepCandidate(
            id=str(uuid.uuid4()),
            subgoal_id=subgoal_id,
            action_type=action_type,
            new_claims=new_claims,
            dependencies=dependencies,
            verification_plan=VerificationPlan(
                stages=stages,
                success_criteria=success_criteria or {},
                enumeration_bound=enumeration_bound,
            ),
            small_case_tests=small_cases or [],
            lean_stub=lean_stub,
            strategy_family=self.strategy_family,
            candidate_hash=candidate_hash,
            branch_id=branch_id,
        )

    @staticmethod
    def _hash_candidate(subgoal_id: str, statements: list[str]) -> str:
        sorted_stmts = sorted(s.strip().lower() for s in statements)
        payload = subgoal_id + "".join(sorted_stmts)
        return hashlib.sha256(payload.encode()).hexdigest()
