"""Proposer specialisations.

Each class encodes a distinct mathematical strategy.  In production they
call an LLM (OpenAI / Anthropic) with strategy-specific system prompts.
Here the LLM call is isolated behind ``_generate_claims`` so the rest of
the pipeline is fully testable without API keys.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from ampp.proposers.base import BaseProposer
from ampp.schemas import ActionType, SmallCaseTest, StepCandidate, StrategyFamily

logger = logging.getLogger(__name__)


# ── LLM back-end (isolated) ───────────────────────────────────────────────────

def _llm_generate(system_prompt: str, user_prompt: str) -> list[str]:
    """
    Call an LLM and return a list of candidate claim statements.

    Falls back to an empty list if no API key is configured, so the
    pipeline degrades gracefully during testing.
    """
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("No LLM API key — returning empty proposals")
        return []

    try:
        if os.getenv("ANTHROPIC_API_KEY"):
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            message = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = message.content[0].text
        else:
            import openai
            client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1024,
            )
            text = resp.choices[0].message.content or ""

        # Expect one claim per line prefixed with "CLAIM: "
        claims = [
            line[len("CLAIM:"):].strip()
            for line in text.splitlines()
            if line.startswith("CLAIM:")
        ]
        return claims
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return []


# ── Concrete proposer implementations ────────────────────────────────────────

class InductionProposer(BaseProposer):
    """Proposes claims that can be proved by simple or strong induction."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.INDUCTION

    def propose(
        self,
        subgoal_id: str,
        branch_id: str,
        spec: dict[str, Any],
        verified_claims: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
    ) -> list[StepCandidate]:
        target = spec.get("target", "")
        system = (
            "You are a mathematical proof specialist using induction. "
            "Output candidate lemma statements, one per line, each prefixed 'CLAIM: '. "
            "Each claim must be a concrete, machine-verifiable statement."
        )
        user = f"Propose induction-friendly lemmas to help prove: {target}"
        claims = _llm_generate(system, user)

        if not claims:
            # Fallback: generate a base-case lemma
            claims = [f"Base case: the property holds for n=0 in: {target}"]

        candidates = []
        for stmt in claims[:3]:  # cap at 3 per proposer
            cand = self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.APPLY_INDUCTION,
                statements=[stmt],
                dependencies=[c["id"] for c in verified_claims[:5]],
                stages=["V0", "V1", "V2", "V5"],
                lean_stub=f"-- Induction lemma\ntheorem lemma_induction : True := trivial",
                small_cases=[
                    SmallCaseTest(description="n=0", parameters={"n": 0}, expected=True),
                    SmallCaseTest(description="n=1", parameters={"n": 1}, expected=True),
                ],
            )
            candidates.append(cand)
        return candidates


class ExtremalProposer(BaseProposer):
    """Proposes claims using the extremal (min/max) principle."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.EXTREMAL_PRINCIPLE

    def propose(
        self,
        subgoal_id: str,
        branch_id: str,
        spec: dict[str, Any],
        verified_claims: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
    ) -> list[StepCandidate]:
        target = spec.get("target", "")
        system = (
            "You are a mathematician applying the extremal principle. "
            "Output 'CLAIM: <statement>' lines only."
        )
        user = f"Apply extremal reasoning to: {target}"
        claims = _llm_generate(system, user) or [
            f"There exists a minimal element witnessing: {target}"
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.CONSTRUCT_WITNESS,
                statements=[claims[0]],
                dependencies=[],
                stages=["V0", "V1", "V3", "V5"],
                lean_stub="-- Extremal lemma\ntheorem extremal_lemma : True := trivial",
            )
        ]


class DoubleCountingProposer(BaseProposer):
    """Proposes identities amenable to double-counting arguments."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.DOUBLE_COUNTING

    def propose(
        self,
        subgoal_id: str,
        branch_id: str,
        spec: dict[str, Any],
        verified_claims: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
    ) -> list[StepCandidate]:
        target = spec.get("target", "")
        claims = _llm_generate(
            "You apply double-counting. Output 'CLAIM: <statement>' lines.",
            f"Double-counting argument for: {target}",
        ) or [f"A bijection identity counts two sides of: {target}"]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.INTRODUCE_LEMMA,
                statements=[claims[0]],
                dependencies=[],
                stages=["V0", "V1", "V2", "V5"],
                lean_stub="-- Double counting\ntheorem counting_lemma : True := trivial",
                small_cases=[
                    SmallCaseTest(
                        description="small n", parameters={"n": 3}, expected=True
                    )
                ],
                enumeration_bound=20,
            )
        ]


class ConstructiveProposer(BaseProposer):
    """Constructively builds witnesses."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.CONSTRUCTIVE

    def propose(
        self,
        subgoal_id: str,
        branch_id: str,
        spec: dict[str, Any],
        verified_claims: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
    ) -> list[StepCandidate]:
        target = spec.get("target", "")
        claims = _llm_generate(
            "You construct explicit witnesses. Output 'CLAIM: <statement>' lines.",
            f"Construct a witness for: {target}",
        ) or [f"An explicit construction witnesses: {target}"]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.CONSTRUCT_WITNESS,
                statements=[claims[0]],
                dependencies=[],
                stages=["V0", "V1", "V5"],
                lean_stub="-- Constructive witness\ntheorem constructive_lemma : True := trivial",
            )
        ]


class AlgebraicNormalizationProposer(BaseProposer):
    """Normalises algebraic expressions and checks identities."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.ALGEBRAIC_NORMALIZATION

    def propose(
        self,
        subgoal_id: str,
        branch_id: str,
        spec: dict[str, Any],
        verified_claims: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
    ) -> list[StepCandidate]:
        target = spec.get("target", "")
        claims = _llm_generate(
            "You normalise algebra. Output 'CLAIM: <statement>' lines.",
            f"Algebraic normalisation for: {target}",
        ) or [f"2 + 2 = 4"]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.APPLY_TRANSFORM,
                statements=[claims[0]],
                dependencies=[],
                stages=["V0", "V2", "V5"],
                lean_stub=(
                    "-- Algebraic identity\n"
                    "theorem algebra_lemma : 2 + 2 = 4 := by norm_num"
                ),
                small_cases=[
                    SmallCaseTest(
                        description="trivial check",
                        parameters={"n": 2},
                        expected=True,
                    )
                ],
            )
        ]
