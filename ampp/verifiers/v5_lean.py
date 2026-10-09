"""V5: check the exact claim as a Lean proposition, with audited axioms.

``lean_stub`` is a proof term beginning with ``by``, not a Lean module.
The generated declaration binds the proof to ``new_claims[0].statement``.
Lean and its imported libraries are trusted; this is not a process sandbox.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ampp.config import cfg
from ampp.schemas import StepCandidate
from ampp.verifiers.result import result

# Custom axioms and sorryAx are never accepted. These are Lean's standard
# logical axioms, also used by Mathlib. native_decide's axiom is not on this list.
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
FORBIDDEN = re.compile(
    r"\b(sorry|admit|sorryAx|axiom|constant|opaque|unsafe|theorem|lemma|def|"
    r"example|namespace|section|end|import|open|export|set_option|attribute|"
    r"syntax|macro|elab|initialize|run_tac|run_elab|native_decide)\b"
)


class LeanVerifier:
    """Mandatory Lean gate with an explicit unavailable outcome."""

    def __init__(self, lean_binary: str | None = None) -> None:
        self._lean = shutil.which(lean_binary or cfg.lean_binary)
        self._cwd = cfg.lean_project or str(Path.cwd())

    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        if len(candidate.new_claims) != 1:
            return result("inconclusive", reason="V5 requires exactly one claim per candidate")
        statement = candidate.new_claims[0].statement.strip()
        proof = candidate.lean_stub.strip()
        if not re.match(r"^by\b", proof):
            return result(
                "inconclusive",
                reason="lean_stub must be a 'by' proof term; legacy theorem stubs require migration",
            )
        # Disallow command injection, commented-out checks, and explicit holes.
        # The axiom audit below is also required: lexical checks alone are not proof.
        for text in (statement, proof):
            if FORBIDDEN.search(text) or any(
                x in text for x in ("--", "/-", "-/", "#", '"', "«", "»", "\x00")
            ):
                return result(
                    "failed",
                    reason="Unsupported declaration, comment, string, or proof escape in Lean input",
                )
        if self._lean is None:
            return result("unavailable", reason="lean_not_found")
        source = self._build_lean_source(candidate)
        passed, details = self._compile(source)
        if passed:
            details.update(
                {
                    "statement": statement,
                    "lean_source": source,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "policy": "lean-kernel-v1",
                }
            )
        return passed, details

    def _build_lean_source(self, candidate: StepCandidate) -> str:
        # Imports are operator configuration, never candidate-controlled.
        imports = "\n".join(f"import {name}" for name in cfg.lean_imports.split() if name)
        statement = candidate.new_claims[0].statement.strip()
        proof = candidate.lean_stub.strip()
        return (
            f"{imports}\n\n"
            f"theorem ampp_claim : (\n{statement}\n) :=\n{proof}\n\n"
            "#print axioms ampp_claim\n"
        )

    def _compile(self, source: str) -> tuple[bool, dict[str, Any]]:
        if self._lean is None:
            return result("unavailable", reason="lean_not_found")
        with tempfile.TemporaryDirectory(prefix="ampp-lean-") as tmpdir:
            lean_file = Path(tmpdir) / "Proof.lean"
            lean_file.write_text(source, encoding="utf-8")
            try:
                completed = subprocess.run(
                    [self._lean, str(lean_file)],
                    capture_output=True,
                    text=True,
                    timeout=cfg.lean_timeout_sec,
                    cwd=self._cwd,
                )
            except subprocess.TimeoutExpired:
                return result("inconclusive", reason="Lean compilation timeout")
            except OSError as exc:
                return result("unavailable", reason=f"Lean invocation error: {exc}")
            output = completed.stdout + "\n" + completed.stderr
            diagnostics = {"stdout": completed.stdout[:6000], "stderr": completed.stderr[:6000]}
            if completed.returncode != 0:
                return result("failed", reason="Lean compilation failed", **diagnostics)
            match = re.search(r"'ampp_claim' depends on axioms: \[([^\]]*)\]", output)
            if match:
                axioms = [s.strip() for s in match.group(1).split(",") if s.strip()]
            elif "'ampp_claim' does not depend on any axioms" in output:
                axioms = []
            else:
                return result(
                    "inconclusive",
                    reason="Lean succeeded but axiom audit was not found",
                    **diagnostics,
                )
            if set(axioms) - ALLOWED_AXIOMS:
                return result(
                    "failed", reason="Unapproved Lean axioms", axioms=axioms, **diagnostics
                )
            if "sorry" in output.lower():
                return result("failed", reason="Lean reported an admitted proof", **diagnostics)
            return result("passed", lean_result="compiled", axioms=axioms, **diagnostics)
