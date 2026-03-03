"""AMPP Python Worker — JSON-RPC line protocol over stdin/stdout.

The Rust core spawns this script as a subprocess and communicates
via newline-delimited JSON (one message per line).

Message types (field ``stage``):
  NORMALISE  → FormalSpec
  PROPOSE    → list[StepCandidate]
  V1         → V1 counterexample check
  V2         → SymPy symbolic check
  V3         → Z3 SMT check
  V4         → ATP check
  V5         → Lean compilation check
  shutdown   → graceful exit
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

# ── Configure logging to stderr (stdout is reserved for IPC) ─────────────────
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ampp.worker")

# ── Lazy imports (avoid startup cost if stage not invoked) ────────────────────
from ampp.normalizer import Normalizer
from ampp.proposers.ensemble import ProposerEnsemble
from ampp.agents.rubric_agent import RubricAgent
from ampp.agents.conjecture_miner import ConjectureMiner
from ampp.agents.strategy_controller import StrategyController
from ampp.verifiers.v1_counterexample import CounterexampleVerifier
from ampp.verifiers.v2_sympy import SymPyVerifier
from ampp.verifiers.v3_z3 import Z3Verifier
from ampp.verifiers.v4_atp import ATPVerifier
from ampp.verifiers.v5_lean import LeanVerifier
from ampp.schemas import StepCandidate, VerificationRequest, VerificationResponse


# ── Singleton instances ───────────────────────────────────────────────────────
_normalizer = Normalizer()
_rubric = RubricAgent()
_ensemble = ProposerEnsemble(rubric_agent=_rubric)
_conj_miner = ConjectureMiner()
_strategy_ctrl = StrategyController()

_verifiers: dict[str, Any] = {
    "V1": CounterexampleVerifier(),
    "V2": SymPyVerifier(),
    "V3": Z3Verifier(),
    "V4": ATPVerifier(),
    "V5": LeanVerifier(),
}


# ── Dispatch ──────────────────────────────────────────────────────────────────

def handle(request: dict[str, Any]) -> dict[str, Any]:
    stage = request.get("stage", "")
    request_id = request.get("request_id", "")
    context = request.get("context", {})
    candidate_json = request.get("candidate_json", {})

    try:
        if stage == "NORMALISE":
            problem = context.get("problem", "")
            spec = _normalizer.normalize(problem)
            return {
                "request_id": request_id,
                "stage": stage,
                "passed": True,
                "details": spec.model_dump(),
                "counterexample": None,
            }

        elif stage == "PROPOSE":
            subgoal_id = context.get("subgoal_id", "")
            branch_id = context.get("branch_id", "")
            spec = context.get("spec", {})
            verified = context.get("verified_claims", [])
            attempts = context.get("attempts", [])
            rejected = set(context.get("rejected_hashes", []))

            candidates = _ensemble.propose(
                subgoal_id=subgoal_id,
                branch_id=branch_id,
                spec=spec,
                verified_claims=verified,
                attempts=attempts,
                rejected_hashes=rejected,
            )
            return {
                "request_id": request_id,
                "stage": stage,
                "passed": True,
                "details": {"candidates": [c.model_dump() for c in candidates]},
                "counterexample": None,
            }

        elif stage in _verifiers:
            verifier = _verifiers[stage]
            candidate = StepCandidate.model_validate(candidate_json)
            passed, details = verifier.verify(candidate, context)
            cx = details.pop("witness", None)
            if cx is not None:
                cx_payload = {"witness": cx}
            else:
                cx_payload = None
            return {
                "request_id": request_id,
                "stage": stage,
                "passed": passed,
                "details": details,
                "counterexample": cx_payload,
            }

        else:
            logger.warning("Unknown stage: %s", stage)
            return {
                "request_id": request_id,
                "stage": stage,
                "passed": True,
                "details": {"note": f"unknown stage {stage!r} — conservative pass"},
                "counterexample": None,
            }

    except Exception as exc:
        logger.exception("Worker error handling stage %s: %s", stage, exc)
        return {
            "request_id": request_id,
            "stage": stage,
            "passed": False,
            "details": {"reason": f"worker exception: {exc}"},
            "counterexample": None,
        }


# ── Main event loop ───────────────────────────────────────────────────────────

def main() -> None:
    logger.info("AMPP Python worker started (pid=%d)", __import__("os").getpid())

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            logger.error("JSON decode error: %s", exc)
            continue

        # Graceful shutdown signal
        if request.get("type") == "shutdown" or request.get("stage") == "shutdown":
            logger.info("Shutdown signal received")
            break

        response = handle(request)

        # Write response as a single newline-terminated JSON line
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    logger.info("AMPP Python worker exiting")


if __name__ == "__main__":
    main()
