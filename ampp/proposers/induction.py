"""
Induction Proposer — generates proof steps using standard and strong induction.
"""

from __future__ import annotations

from ampp.config import ActionType, StrategyFamily
from ampp.models.proof_state import ProofState
from ampp.models.state import FormalSpec, Subgoal
from ampp.models.step_candidate import (
    SmallCaseTest,
    StepCandidate,
    VerificationPlan,
)
from ampp.proposers.base import BaseProposer


class InductionProposer(BaseProposer):
    name = "induction"
    strategy_family = StrategyFamily.INDUCTION

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on INDUCTION strategies:\n"
                "- Standard mathematical induction on a natural number\n"
                "- Identify the induction variable\n"
                "- State the base case explicitly\n"
                "- State the inductive step: P(k) → P(k+1)\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        # Heuristic: generate base case + inductive step skeleton
        candidates: list[StepCandidate] = []

        # Base case
        base = StepCandidate(
            subgoal_id=subgoal.id,
            action_type=ActionType.INDUCTION_STEP,
            new_claims=(
                f"Base case (n=0 or n=1): {subgoal.statement}",
            ),
            dependencies=(),
            verification_plan=VerificationPlan(
                applicable_verifiers=("V1", "V2"),
                success_criteria="Direct computation for small cases",
                falsification_bounds="n ≤ 5",
            ),
            small_case_tests=(
                SmallCaseTest(
                    parameters={"n": 0},
                    description="Base case n=0",
                ),
                SmallCaseTest(
                    parameters={"n": 1},
                    description="Base case n=1",
                ),
            ),
            lean_stub=(
                "theorem base_case : P 0 := by\n"
                "  sorry\n"
            ),
            strategy_family=self.strategy_family,
            proposer_name=self.name,
        )
        candidates.append(base)

        # Inductive step
        step = StepCandidate(
            subgoal_id=subgoal.id,
            action_type=ActionType.INDUCTION_STEP,
            new_claims=(
                f"Inductive step: P(k) → P(k+1) for: {subgoal.statement}",
            ),
            dependencies=(),
            verification_plan=VerificationPlan(
                applicable_verifiers=("V2", "V3", "V5"),
                success_criteria="Lean compilation succeeds",
                z3_encoding_hint="Assume P(k), derive P(k+1)",
            ),
            small_case_tests=(
                SmallCaseTest(
                    parameters={"k": 5, "k+1": 6},
                    description="Verify step k=5 → k+1=6",
                ),
            ),
            lean_stub=(
                "theorem inductive_step (k : ℕ) (ih : P k) : "
                "P (k + 1) := by\n"
                "  sorry\n"
            ),
            strategy_family=self.strategy_family,
            proposer_name=self.name,
        )
        candidates.append(step)

        return self._filter_complete(candidates)


class StrongInductionProposer(BaseProposer):
    name = "strong_induction"
    strategy_family = StrategyFamily.STRONG_INDUCTION

    def propose(
        self,
        subgoal: Subgoal,
        spec: FormalSpec,
        state: ProofState,
    ) -> list[StepCandidate]:
        if self.llm_assist:
            prompt = self._build_prompt(subgoal, spec, state)
            prompt += (
                "\n\nFocus on STRONG INDUCTION:\n"
                "- Assume P(j) for all j < k\n"
                "- Derive P(k)\n"
                "- Identify the well-ordering used\n"
            )
            response = self.llm_assist(prompt)
            return self._parse_llm_candidates(response, subgoal)

        candidates = [
            StepCandidate(
                subgoal_id=subgoal.id,
                action_type=ActionType.INDUCTION_STEP,
                new_claims=(
                    f"Strong induction: (∀ j < k, P(j)) → P(k) for: "
                    f"{subgoal.statement}",
                ),
                dependencies=(),
                verification_plan=VerificationPlan(
                    applicable_verifiers=("V1", "V2", "V3", "V5"),
                    success_criteria="Lean compilation with Nat.strongRecOn",
                    z3_encoding_hint=(
                        "Universal quantifier over j < k with P(j)"
                    ),
                    falsification_bounds="k ≤ 10",
                ),
                small_case_tests=(
                    SmallCaseTest(
                        parameters={"k": 3},
                        description="Strong induction step at k=3",
                    ),
                ),
                lean_stub=(
                    "theorem strong_ind (k : ℕ) "
                    "(ih : ∀ j, j < k → P j) : P k := by\n"
                    "  sorry\n"
                ),
                strategy_family=self.strategy_family,
                proposer_name=self.name,
            )
        ]
        return self._filter_complete(candidates)
