"""
Pipeline Logging (Section 16, 17)

Structured logging for full reproducibility and artifact generation.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PipelineLogger:
    """
    Structured logger for the AMPP pipeline.

    Logs events as JSON lines for machine-parseable audit trails.
    Also configures standard Python logging.
    """

    def __init__(
        self,
        log_dir: str | Path,
        level: int = logging.INFO,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.event_log_path = self.log_dir / "events.jsonl"
        self.events: list[dict[str, Any]] = []

        # Configure Python logging
        self._configure_logging(level)

    def _configure_logging(self, level: int) -> None:
        """Configure root logger with console and file handlers."""
        root = logging.getLogger("ampp")
        root.setLevel(level)

        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(level)
        console.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(console)

        # File handler
        file_handler = logging.FileHandler(
            self.log_dir / "pipeline.log"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )
        )
        root.addHandler(file_handler)

    def log_event(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Log a structured event."""
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "type": event_type,
            "data": data or {},
        }
        self.events.append(event)

        # Write to JSONL file
        with open(self.event_log_path, "a") as f:
            f.write(json.dumps(event) + "\n")

    def log_iteration(
        self,
        iteration: int,
        state_snapshot: dict[str, Any],
        candidates_proposed: int,
        candidates_passed_rubric: int,
        verified: int,
        rejected: int,
    ) -> None:
        """Log an iteration summary."""
        self.log_event(
            "iteration",
            {
                "iteration": iteration,
                "state": state_snapshot,
                "candidates_proposed": candidates_proposed,
                "candidates_passed_rubric": candidates_passed_rubric,
                "verified": verified,
                "rejected": rejected,
            },
        )

    def log_verification(
        self,
        claim_id: str,
        result: str,
        stage: str,
        details: str = "",
    ) -> None:
        """Log a verification event."""
        self.log_event(
            "verification",
            {
                "claim_id": claim_id,
                "result": result,
                "stage": stage,
                "details": details,
            },
        )

    def log_commit(
        self,
        claim_id: str,
        action: str,
        commit_hash: str,
    ) -> None:
        """Log a two-phase commit event."""
        self.log_event(
            "commit",
            {
                "claim_id": claim_id,
                "action": action,
                "commit_hash": commit_hash,
            },
        )

    def flush(self) -> None:
        """Flush all logs."""
        for handler in logging.getLogger("ampp").handlers:
            handler.flush()
