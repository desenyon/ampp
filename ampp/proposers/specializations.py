"""Proposer specialisations — all 10 strategy families.

Each class encodes a distinct mathematical strategy.  LLM calls go through
the shared ``ampp.llm`` module which resolves the active provider (OpenAI
default, Anthropic opt-in, OpenClaw via OPENAI_BASE_URL) at runtime.

The LLM back-end is isolated behind ``llm_generate_claims`` so the entire
pipeline remains testable without API keys (NullProvider returns []).
"""
from __future__ import annotations

import logging
from typing import Any

from ampp.llm import llm_generate_claims
from ampp.proposers.base import BaseProposer
from ampp.schemas import ActionType, SmallCaseTest, StepCandidate, StrategyFamily

logger = logging.getLogger(__name__)


# ── Shared prompt helpers ─────────────────────────────────────────────────────

_BASE_SYSTEM = (
    "You are an expert mathematician and formal proof engineer working inside an "
    "autonomous proof pipeline (AMPP).  Your task is to propose precise, minimal, "
    "machine-verifiable lemma statements that help prove the stated target.\n\n"
    "Rules:\n"
    "• Each claim must be a single self-contained mathematical statement.\n"
    "• Prefer statements expressible in Lean 4 / Mathlib.\n"
    "• Do not bundle multiple independent ideas into one claim.\n"
    "• Use standard notation; avoid ambiguous natural language.\n"
)


def _user_ctx(target: str, verified: list[dict[str, Any]], strategy_hint: str) -> str:
    dep_summary = ""
    if verified:
        stmts = [v.get("statement", "") for v in verified[:5] if v.get("statement")]
        if stmts:
            dep_summary = "\n\nAlready verified:\n" + "\n".join(f"  • {s}" for s in stmts)
    return (
        f"Target theorem: {target}\n"
        f"Strategy: {strategy_hint}"
        + dep_summary
    )


# ── Concrete proposer implementations ────────────────────────────────────────

class InductionProposer(BaseProposer):
    """Proposes claims amenable to simple mathematical induction."""

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
            _BASE_SYSTEM
            + "\nFocus: identify an inductive invariant P(n) such that "
            "P(0) is trivially true and P(n) → P(n+1) implies the target."
        )
        user = _user_ctx(target, verified_claims, "simple induction")
        claims = llm_generate_claims(system, user) or [
            f"Base case: the property holds for n=0 in: {target}",
            f"Inductive step: if P(n) holds then P(n+1) holds for: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.APPLY_INDUCTION,
                statements=[stmt],
                dependencies=[c["id"] for c in verified_claims[:5]],
                stages=["V0", "V1", "V2", "V5"],
                lean_stub=(
                    "-- Induction lemma\n"
                    "theorem lemma_induction (n : ℕ) : True := trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="n=0", parameters={"n": 0}, expected=True),
                    SmallCaseTest(description="n=1", parameters={"n": 1}, expected=True),
                    SmallCaseTest(description="n=2", parameters={"n": 2}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]


class StrongInductionProposer(BaseProposer):
    """Proposes claims proved by strong (complete) induction."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.STRONG_INDUCTION

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
            _BASE_SYSTEM
            + "\nFocus: strong induction — assume P(k) for all k < n and derive P(n). "
            "Identify the well-founded relation and the inductive hypothesis."
        )
        user = _user_ctx(target, verified_claims, "strong/complete induction")
        claims = llm_generate_claims(system, user) or [
            f"Strong inductive step: assuming P(k) for all k<n implies P(n) for: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.APPLY_INDUCTION,
                statements=[stmt],
                dependencies=[c["id"] for c in verified_claims[:5]],
                stages=["V0", "V1", "V5"],
                lean_stub=(
                    "-- Strong induction\n"
                    "theorem strong_ind (n : ℕ) : True := trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="n=0", parameters={"n": 0}, expected=True),
                    SmallCaseTest(description="n=3", parameters={"n": 3}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]


class MinimalCounterexampleProposer(BaseProposer):
    """Proof by minimal counterexample (well-ordering principle)."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.MINIMAL_COUNTEREXAMPLE

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
            _BASE_SYSTEM
            + "\nFocus: assume a minimal counterexample exists and derive a contradiction. "
            "Show that its existence leads to a smaller counterexample."
        )
        user = _user_ctx(target, verified_claims, "minimal counterexample / well-ordering")
        claims = llm_generate_claims(system, user) or [
            f"Assume a minimal n violates the property; derive a contradiction for: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.INTRODUCE_LEMMA,
                statements=[stmt],
                dependencies=[c["id"] for c in verified_claims[:3]],
                stages=["V0", "V1", "V3", "V5"],
                lean_stub=(
                    "-- Minimal counterexample\n"
                    "theorem no_min_cx : True := trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="n=1", parameters={"n": 1}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]


class ExtremalProposer(BaseProposer):
    """Proposes claims using the extremal (min/max element) principle."""

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
            _BASE_SYSTEM
            + "\nFocus: identify a minimal or maximal element in a non-empty bounded set "
            "and derive structural properties from its extremality."
        )
        user = _user_ctx(target, verified_claims, "extremal principle")
        claims = llm_generate_claims(system, user) or [
            f"There exists a minimal element witnessing the extremal property in: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.CONSTRUCT_WITNESS,
                statements=[stmt],
                dependencies=[],
                stages=["V0", "V1", "V3", "V5"],
                lean_stub=(
                    "-- Extremal element\n"
                    "theorem extremal_exists : True := trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="n=2", parameters={"n": 2}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]


class InvariantMonovariantProposer(BaseProposer):
    """Proposes invariants and monovariants for combinatorial processes."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.INVARIANT_MONOVARIANT

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
            _BASE_SYSTEM
            + "\nFocus: find a quantity that is preserved (invariant) or strictly "
            "monotone (monovariant) under the described process/operation.  "
            "State the invariant precisely and explain why it is preserved."
        )
        user = _user_ctx(target, verified_claims, "invariant / monovariant")
        claims = llm_generate_claims(system, user) or [
            f"The quantity Q is invariant under each step of the process in: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.INTRODUCE_LEMMA,
                statements=[stmt],
                dependencies=[c["id"] for c in verified_claims[:3]],
                stages=["V0", "V1", "V2", "V5"],
                lean_stub=(
                    "-- Invariant preservation\n"
                    "theorem invariant_preserved : True := trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="step=0", parameters={"step": 0}, expected=True),
                    SmallCaseTest(description="step=1", parameters={"step": 1}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]


class AlgebraicNormalizationProposer(BaseProposer):
    """Proposes algebraic identities and normalization steps."""

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
        system = (
            _BASE_SYSTEM
            + "\nFocus: reduce the statement to a canonical algebraic form using "
            "known identities, polynomial manipulations, generating functions, "
            "or modular arithmetic reductions."
        )
        user = _user_ctx(target, verified_claims, "algebraic normalization")
        claims = llm_generate_claims(system, user) or [
            f"The expression can be reduced to a canonical normal form: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.APPLY_TRANSFORM,
                statements=[stmt],
                dependencies=[c["id"] for c in verified_claims[:5]],
                stages=["V0", "V1", "V2", "V3", "V5"],
                lean_stub=(
                    "-- Algebraic normalization\n"
                    "theorem alg_normal : True := by ring"
                ),
                small_cases=[
                    SmallCaseTest(description="n=1", parameters={"n": 1}, expected=True),
                    SmallCaseTest(description="n=2", parameters={"n": 2}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]


class DoubleCountingProposer(BaseProposer):
    """Proposes identities via double-counting / bijection arguments."""

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
        system = (
            _BASE_SYSTEM
            + "\nFocus: count a common quantity in two different ways, or establish "
            "a bijection between two finite sets to prove their cardinalities are equal."
        )
        user = _user_ctx(target, verified_claims, "double counting / bijection")
        claims = llm_generate_claims(system, user) or [
            f"A bijection between sets A and B establishes equality relevant to: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.INTRODUCE_LEMMA,
                statements=[stmt],
                dependencies=[],
                stages=["V0", "V1", "V2", "V5"],
                lean_stub=(
                    "-- Double counting\n"
                    "theorem double_count : True := trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="n=2", parameters={"n": 2}, expected=True),
                    SmallCaseTest(description="n=3", parameters={"n": 3}, expected=True),
                ],
                enumeration_bound=20,
            )
            for stmt in claims[:3]
        ]


class ConstructiveProposer(BaseProposer):
    """Constructively builds explicit witnesses for existential claims."""

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
        system = (
            _BASE_SYSTEM
            + "\nFocus: construct an explicit, computable witness.  "
            "Define a concrete object or algorithm that satisfies the existential claim."
        )
        user = _user_ctx(target, verified_claims, "constructive witness")
        claims = llm_generate_claims(system, user) or [
            f"An explicit construction witnesses: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.CONSTRUCT_WITNESS,
                statements=[stmt],
                dependencies=[c["id"] for c in verified_claims[:3]],
                stages=["V0", "V1", "V5"],
                lean_stub=(
                    "-- Constructive witness\n"
                    "theorem constructive_lem : True := trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="n=1", parameters={"n": 1}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]


class GraphTranslationProposer(BaseProposer):
    """Translates combinatorial problems into graph-theoretic language."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.GRAPH_TRANSLATION

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
            _BASE_SYSTEM
            + "\nFocus: model the combinatorial structure as a graph (or hypergraph). "
            "Translate the claim into a statement about degrees, paths, colourings, "
            "cliques, independent sets, or graph homomorphisms."
        )
        user = _user_ctx(target, verified_claims, "graph translation")
        claims = llm_generate_claims(system, user) or [
            f"The problem is equivalent to a graph-theoretic statement: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.APPLY_TRANSFORM,
                statements=[stmt],
                dependencies=[],
                stages=["V0", "V1", "V3", "V5"],
                lean_stub=(
                    "-- Graph translation\n"
                    "theorem graph_lemma : True := trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="n=3", parameters={"n": 3}, expected=True),
                    SmallCaseTest(description="n=4", parameters={"n": 4}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]


class ContradictionProposer(BaseProposer):
    """Proof by contradiction — assumes negation and derives False."""

    @property
    def strategy_family(self) -> StrategyFamily:
        return StrategyFamily.CONTRADICTION

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
            _BASE_SYSTEM
            + "\nFocus: assume the negation of the claim and derive a contradiction. "
            "Identify the key intermediate statement whose truth with the negation "
            "leads directly to False or ⊥."
        )
        user = _user_ctx(target, verified_claims, "proof by contradiction")
        claims = llm_generate_claims(system, user) or [
            f"Assuming the negation of the target leads to a contradiction in: {target}",
        ]
        return [
            self._build_candidate(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                action_type=ActionType.INTRODUCE_LEMMA,
                statements=[stmt],
                dependencies=[c["id"] for c in verified_claims[:5]],
                stages=["V0", "V1", "V3", "V5"],
                lean_stub=(
                    "-- Proof by contradiction\n"
                    "theorem contra_lemma : True := by\n"
                    "  intro h\n"
                    "  trivial"
                ),
                small_cases=[
                    SmallCaseTest(description="n=1", parameters={"n": 1}, expected=True),
                ],
            )
            for stmt in claims[:3]
        ]



# ─────────────────────────────────────────────────────────────────────────────
# All 10 strategy-family proposers are defined above.
# Import them directly; no module-level functions remain.
