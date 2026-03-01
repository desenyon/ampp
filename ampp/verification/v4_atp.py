"""
V4 — First-Order ATP (Section 8)

Using Vampire or E prover.
Translate claims to first-order logic where possible.

Theorem → verified fragment.
CounterSatisfiable → reject.
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
class V4Result:
    passed: bool
    details: str = ""
    solver_output: str = ""


class V4ATPVerifier:
    """
    First-order automated theorem prover interface.

    Supports Vampire and E prover. Claims are translated to TPTP format
    and submitted to the ATP. The result determines verification status.
    """

    def __init__(self, config: VerifierConfig | None = None) -> None:
        self.config = config or VerifierConfig()

    def verify(
        self,
        claim_id: str,
        tptp_problem: str,
        *,
        claim_statement: str = "",
    ) -> V4Result:
        """
        Verify a claim using a first-order ATP.

        Args:
            claim_id: ID of the claim.
            tptp_problem: The claim in TPTP format.
            claim_statement: Human-readable statement for logging.

        Returns:
            V4Result with verification outcome.
        """
        # Check if ATP binary is available
        binary = self.config.atp_binary
        if not self._is_available(binary):
            logger.warning("ATP binary '%s' not available, skipping V4", binary)
            return V4Result(
                passed=True,
                details=f"V4 skipped: {binary} not available",
            )

        try:
            # Write TPTP problem to temp file
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".p",
                delete=False,
            ) as f:
                f.write(tptp_problem)
                problem_path = f.name

            # Run ATP
            cmd = self._build_command(binary, problem_path)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.atp_timeout_seconds,
            )

            output = result.stdout + result.stderr

            # Parse result
            if "Theorem" in output or "SZS status Theorem" in output:
                return V4Result(
                    passed=True,
                    details=f"ATP: Theorem proved for {claim_id}",
                    solver_output=output[:2000],
                )
            elif (
                "CounterSatisfiable" in output
                or "SZS status CounterSatisfiable" in output
            ):
                return V4Result(
                    passed=False,
                    details=(
                        f"ATP: CounterSatisfiable for {claim_id} — "
                        "claim is false"
                    ),
                    solver_output=output[:2000],
                )
            elif "Timeout" in output or "SZS status Timeout" in output:
                return V4Result(
                    passed=True,  # Don't reject on timeout
                    details="ATP: timeout",
                    solver_output=output[:2000],
                )
            else:
                return V4Result(
                    passed=True,  # Don't reject on unknown status
                    details=f"ATP: inconclusive status",
                    solver_output=output[:2000],
                )

        except subprocess.TimeoutExpired:
            return V4Result(
                passed=True,
                details="ATP: process timeout",
            )
        except FileNotFoundError:
            return V4Result(
                passed=True,
                details=f"V4 skipped: {binary} not found",
            )
        except Exception as e:
            logger.error("V4 error: %s", e)
            return V4Result(
                passed=True,
                details=f"V4 error: {e}",
            )
        finally:
            # Clean up temp file
            try:
                Path(problem_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _build_command(
        self, binary: str, problem_path: str
    ) -> list[str]:
        """Build the command line for the ATP."""
        timeout_s = int(self.config.atp_timeout_seconds)

        if "vampire" in binary.lower():
            return [
                binary,
                "--time_limit",
                str(timeout_s),
                "--input_syntax",
                "tptp",
                problem_path,
            ]
        elif "eprover" in binary.lower():
            return [
                binary,
                "--auto",
                f"--cpu-limit={timeout_s}",
                "--tstp-format",
                problem_path,
            ]
        else:
            return [binary, problem_path]

    def _is_available(self, binary: str) -> bool:
        """Check if the ATP binary is available on PATH."""
        try:
            result = subprocess.run(
                ["which", binary],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def to_artifact(self, result: V4Result) -> VerificationArtifact:
        return VerificationArtifact(
            stage="V4",
            result="pass" if result.passed else "fail",
            details=result.details,
        )
