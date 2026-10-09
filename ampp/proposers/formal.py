"""Generate a proof term for an explicit, caller-owned Lean target."""

from typing import Any

from ampp.config import cfg
from ampp.llm import NullProvider, get_provider
from ampp.proposers.base import BaseProposer
from ampp.schemas import ActionType, StepCandidate, StrategyFamily


class FormalProofProposer(BaseProposer):
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
        if not spec.get("formal_target"):
            return []
        provider = get_provider()
        if isinstance(provider, NullProvider):
            return []
        target = spec["target"]
        failures = [a.get("failure_reason", "") for a in attempts[-5:]]
        response = provider.complete_json(
            "Return a JSON object with a single field proof, a Lean 4 proof term beginning with by. "
            "Prove the exact supplied proposition. Do not return a theorem declaration or change the proposition. "
            "Do not use sorry, admit, axioms, native_decide, commands, comments, or strings. "
            f"Available imports: {cfg.lean_imports or 'Lean core only'}. "
            "If you cannot prove it, return an empty proof.",
            f"Proposition:\n{target}\nRecent failures:\n{failures}",
            max_tokens=cfg.llm_max_tokens,
            temperature=cfg.llm_temperature,
        )
        if not isinstance(response, dict) or not isinstance(response.get("proof"), str):
            return []
        proof = response["proof"].strip()
        if not proof:
            return []
        return [
            self._build_candidate(
                subgoal_id, branch_id, ActionType.INTRODUCE_LEMMA, [target], [], ["V0", "V5"], proof
            )
        ]
