"""
V5 — Lean Proof Checker (Section 8)

Generate Lean lemma. Attempt local compilation.
If compilation succeeds → verified.
If fails → invoke Lemma Minimizer, retry.

Lean compilation is MANDATORY for final verification.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ampp.config import VerifierConfig
from ampp.models.state import VerificationArtifact

logger = logging.getLogger(__name__)


@dataclass
class V5Result:
    passed: bool
    details: str = ""
    lean_output: str = ""
    lean_errors: list[str] | None = None
    lean_file_path: str = ""


class V5LeanChecker:
    """
    Lean 4 proof checker.

    Compiles Lean code and checks for errors. This is the final
    authority — a claim is verified if and only if Lean compiles
    the corresponding proof without errors.
    """

    def __init__(self, config: VerifierConfig | None = None) -> None:
        self.config = config or VerifierConfig()

    def check(
        self,
        claim_id: str,
        lean_code: str,
        *,
        claim_statement: str = "",
    ) -> V5Result:
        """
        Compile Lean code and check for errors.

        Args:
            claim_id: ID of the claim being verified.
            lean_code: Complete Lean 4 source code.
            claim_statement: For logging.

        Returns:
            V5Result. passed=True only if Lean compiles cleanly.
        """
        project_dir = self.config.lean_project_dir
        if not project_dir:
            return self._check_standalone(claim_id, lean_code)

        return self._check_in_project(
            claim_id, lean_code, project_dir
        )

    def _check_standalone(
        self, claim_id: str, lean_code: str
    ) -> V5Result:
        """
        Check Lean code by writing to a temp file and running lean.
        """
        if not self._lean_available():
            logger.warning("Lean not available, skipping V5")
            return V5Result(
                passed=False,
                details="V5: Lean not available (required for verification)",
            )

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".lean",
                delete=False,
            ) as f:
                f.write(lean_code)
                lean_path = f.name

            result = subprocess.run(
                ["lean", lean_path],
                capture_output=True,
                text=True,
                timeout=self.config.lean_timeout_seconds,
            )

            output = result.stdout + result.stderr
            errors = self._extract_errors(output)

            if result.returncode == 0 and not errors:
                return V5Result(
                    passed=True,
                    details=f"Lean compilation successful for {claim_id}",
                    lean_output=output[:3000],
                    lean_file_path=lean_path,
                )
            else:
                return V5Result(
                    passed=False,
                    details=(
                        f"Lean compilation failed for {claim_id}: "
                        f"{len(errors)} errors"
                    ),
                    lean_output=output[:3000],
                    lean_errors=errors,
                    lean_file_path=lean_path,
                )

        except subprocess.TimeoutExpired:
            return V5Result(
                passed=False,
                details="Lean compilation timeout",
            )
        except Exception as e:
            logger.error("V5 error: %s", e)
            return V5Result(
                passed=False,
                details=f"V5 error: {e}",
            )

    def _check_in_project(
        self,
        claim_id: str,
        lean_code: str,
        project_dir: str,
    ) -> V5Result:
        """
        Check Lean code within an existing Lean project
        (with lakefile and mathlib).
        """
        proj = Path(project_dir)
        if not proj.exists():
            return V5Result(
                passed=False,
                details=f"Lean project dir not found: {project_dir}",
            )

        # Write the proof file into the project
        proof_file = proj / "AMPPProof.lean"
        proof_file.write_text(lean_code)

        try:
            result = subprocess.run(
                ["lake", "build"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=self.config.lean_timeout_seconds,
            )

            output = result.stdout + result.stderr
            errors = self._extract_errors(output)

            if result.returncode == 0 and not errors:
                return V5Result(
                    passed=True,
                    details=f"Lean project build success for {claim_id}",
                    lean_output=output[:3000],
                    lean_file_path=str(proof_file),
                )
            else:
                return V5Result(
                    passed=False,
                    details=(
                        f"Lean project build failed: {len(errors)} errors"
                    ),
                    lean_output=output[:3000],
                    lean_errors=errors,
                    lean_file_path=str(proof_file),
                )

        except subprocess.TimeoutExpired:
            return V5Result(
                passed=False,
                details="Lean build timeout",
            )
        except Exception as e:
            logger.error("V5 project build error: %s", e)
            return V5Result(
                passed=False,
                details=f"V5 error: {e}",
            )

    def _extract_errors(self, output: str) -> list[str]:
        """Extract error messages from Lean output."""
        errors: list[str] = []
        for line in output.splitlines():
            if "error" in line.lower() and "sorry" not in line.lower():
                errors.append(line.strip())
            elif "sorry" in line.lower():
                errors.append(f"SORRY: {line.strip()}")
        return errors

    def _lean_available(self) -> bool:
        """Check if lean binary is available."""
        try:
            result = subprocess.run(
                ["lean", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def to_artifact(self, result: V5Result) -> VerificationArtifact:
        return VerificationArtifact(
            stage="V5",
            result="pass" if result.passed else "fail",
            details=result.details,
            log_path=result.lean_file_path,
        )
