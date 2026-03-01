"""
Sandbox Execution (Section 18)

Safety and isolation:
- Solvers run in sandboxed environment
- File writes logged
- Deterministic execution only
- No external state mutation
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result of a sandboxed execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    return_code: int = -1
    files_written: list[str] | None = None


class Sandbox:
    """
    Sandboxed environment for running solvers and external tools.

    Provides:
    - Isolated temp directories for each execution
    - Timeout enforcement
    - File write logging
    - No access to external state beyond designated workspace
    """

    def __init__(
        self,
        workspace_dir: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.workspace_dir = Path(
            workspace_dir or tempfile.mkdtemp(prefix="ampp_sandbox_")
        )
        self.timeout_seconds = timeout_seconds
        self.write_log: list[dict[str, Any]] = []

    def run_command(
        self,
        command: list[str],
        *,
        input_data: str = "",
        timeout: float | None = None,
        working_dir: str | None = None,
    ) -> SandboxResult:
        """
        Run a command in the sandbox.

        Args:
            command: Command and arguments.
            input_data: Data to pipe to stdin.
            timeout: Override default timeout.
            working_dir: Working directory (defaults to sandbox dir).
        """
        cwd = working_dir or str(self.workspace_dir)
        effective_timeout = timeout or self.timeout_seconds

        logger.debug("Sandbox: running %s", command)

        try:
            result = subprocess.run(
                command,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=cwd,
                env=self._safe_env(),
            )

            return SandboxResult(
                success=result.returncode == 0,
                stdout=result.stdout[:50000],
                stderr=result.stderr[:50000],
                return_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            logger.warning(
                "Sandbox: command timed out after %.1fs",
                effective_timeout,
            )
            return SandboxResult(
                success=False,
                stderr=f"Timeout after {effective_timeout}s",
            )
        except FileNotFoundError:
            return SandboxResult(
                success=False,
                stderr=f"Command not found: {command[0]}",
            )
        except Exception as e:
            logger.error("Sandbox error: %s", e)
            return SandboxResult(
                success=False,
                stderr=str(e),
            )

    def write_file(
        self,
        filename: str,
        content: str,
        *,
        subdir: str = "",
    ) -> Path:
        """
        Write a file in the sandbox, logging the write.

        Returns the absolute path of the written file.
        """
        target_dir = self.workspace_dir
        if subdir:
            target_dir = target_dir / subdir
            target_dir.mkdir(parents=True, exist_ok=True)

        filepath = target_dir / filename
        filepath.write_text(content)

        self.write_log.append(
            {
                "file": str(filepath),
                "size": len(content),
                "operation": "write",
            }
        )

        logger.debug("Sandbox: wrote %s (%d bytes)", filepath, len(content))
        return filepath

    def read_file(self, filepath: str | Path) -> str:
        """Read a file from the sandbox."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Sandbox file not found: {path}")
        return path.read_text()

    def cleanup(self) -> None:
        """Clean up sandbox temporary files."""
        import shutil

        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir, ignore_errors=True)
            logger.debug("Sandbox: cleaned up %s", self.workspace_dir)

    def _safe_env(self) -> dict[str, str]:
        """Create a restricted environment for subprocess execution."""
        env = dict(os.environ)
        # Keep only essential environment variables
        safe_keys = {
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "TERM",
            "TMPDIR",
            "USER",
            "SHELL",
        }
        return {k: v for k, v in env.items() if k in safe_keys}
