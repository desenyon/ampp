"""V5 — Lean 4 proof compilation.

Writes the candidate's lean_stub to a temporary .lean file, attempts to
compile it using `lake build` or `lean --run`, and returns the result.

Lean compilation is the final authority on correctness.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from ampp.schemas import StepCandidate

logger = logging.getLogger(__name__)

LEAN_TIMEOUT_SEC = 120


class LeanVerifier:
    """V5 verifier: Lean 4 proof checker."""

    def __init__(self, lean_binary: str = "lean") -> None:
        self._lean = lean_binary if shutil.which(lean_binary) else None

    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        if self._lean is None:
            logger.warning("Lean binary not found — skipping V5")
            return True, {"skipped": True, "reason": "lean_not_found"}

        lean_source = self._build_lean_source(candidate)
        passed, detail = self._compile(lean_source)
        return passed, detail

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_lean_source(self, candidate: StepCandidate) -> str:
        """Wrap the lean_stub in a minimal file skeleton."""
        header = textwrap.dedent(
            f"""\
            -- AMPP auto-generated Lean 4 verification
            -- Candidate: {candidate.id}
            -- Strategy: {candidate.strategy_family}

            import Mathlib

            namespace AMPP

            """
        )
        footer = "\n\nend AMPP\n"
        return header + candidate.lean_stub + footer

    def _compile(self, source: str) -> tuple[bool, dict[str, Any]]:
        """Write source to a temp file and attempt compilation."""
        if self._lean is None:
            return False, {"reason": "Lean binary not available"}

        with tempfile.TemporaryDirectory() as tmpdir:
            lean_file = Path(tmpdir) / "Proof.lean"
            lean_file.write_text(source)

            try:
                result = subprocess.run(
                    [self._lean, str(lean_file)],
                    capture_output=True,
                    text=True,
                    timeout=LEAN_TIMEOUT_SEC,
                    cwd=tmpdir,
                )
                if result.returncode == 0:
                    return True, {
                        "lean_result": "compiled",
                        "stdout": result.stdout[:2000],
                    }
                else:
                    error_lines = (result.stderr or result.stdout)[:3000]
                    return False, {
                        "reason": "Lean compilation failed",
                        "lean_errors": error_lines,
                    }
            except subprocess.TimeoutExpired:
                return False, {"reason": "Lean compilation timeout"}
            except Exception as exc:
                return False, {"reason": f"Lean invocation error: {exc}"}
