"""
Output Artifact Generator (Section 17)

Final proof requires:
- solution.lean (compiles locally)
- solution.md
- proof_graph.json
- verification_log.json
- rejected_claims.json
- run_manifest.json

No solution is accepted without reproducible artifacts.
"""

from __future__ import annotations

import json
import logging
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ampp.models.proof_state import ProofState
from ampp.models.state import FormalSpec
from ampp.utils.hashing import compute_hash

logger = logging.getLogger(__name__)


class ArtifactGenerator:
    """
    Generates all required output artifacts for a proof run.

    Artifacts are written to the output directory and are required
    for the proof to be considered complete.
    """

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(
        self,
        state: ProofState,
        spec: FormalSpec,
        *,
        config_dict: dict[str, Any] | None = None,
        pipeline_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Path]:
        """
        Generate all output artifacts.

        Returns mapping from artifact name to file path.
        """
        artifacts: dict[str, Path] = {}

        artifacts["solution.lean"] = self._generate_solution_lean(
            state
        )
        artifacts["solution.md"] = self._generate_solution_md(
            state, spec
        )
        artifacts["proof_graph.json"] = self._generate_proof_graph(
            state
        )
        artifacts["verification_log.json"] = (
            self._generate_verification_log(state)
        )
        artifacts["rejected_claims.json"] = (
            self._generate_rejected_claims(state)
        )
        artifacts["run_manifest.json"] = self._generate_run_manifest(
            state,
            spec,
            config_dict=config_dict,
            artifacts=artifacts,
        )

        logger.info(
            "Generated %d artifacts in %s",
            len(artifacts),
            self.output_dir,
        )
        return artifacts

    def _generate_solution_lean(self, state: ProofState) -> Path:
        """Generate solution.lean with all verified claims."""
        path = self.output_dir / "solution.lean"

        lines: list[str] = [
            "/-!",
            "# AMPP Generated Proof",
            f"# Generated: {datetime.now(UTC).isoformat()}",
            f"# Verified claims: {len(state.verified_claims)}",
            "-/",
            "",
            "import Mathlib",
            "",
        ]

        # Add definitions
        for defn in state.definitions.values():
            if defn.lean_name:
                lines.append(f"-- Definition: {defn.statement}")
                lines.append("")

        # Add verified claims in dependency order
        verified = sorted(
            state.verified_claims,
            key=lambda c: c.created_at,
        )

        for claim in verified:
            lines.append(f"-- Claim: {claim.statement}")
            lines.append(f"-- Status: {claim.status}")
            lines.append(f"-- Strategy: {claim.strategy_family}")
            if claim.lean_code:
                lines.append(claim.lean_code)
            else:
                lines.append(f"-- (no Lean code available)")
            lines.append("")

        path.write_text("\n".join(lines))
        return path

    def _generate_solution_md(
        self, state: ProofState, spec: FormalSpec
    ) -> Path:
        """Generate solution.md with human-readable proof summary."""
        path = self.output_dir / "solution.md"

        lines: list[str] = [
            "# Proof Solution",
            "",
            f"**Generated:** {datetime.now(UTC).isoformat()}",
            "",
            "## Problem",
            "",
            f"**Raw statement:** {spec.raw_statement}",
            "",
            f"**Canonical form:** {spec.canonical_form}",
            "",
            "## Variables",
            "",
        ]

        for v in spec.variables:
            lines.append(f"- `{v.name}` : `{v.domain}`")

        lines.extend([
            "",
            "## Proof Structure",
            "",
            f"**Verified claims:** {len(state.verified_claims)}",
            f"**Rejected claims:** {len(state.rejected_claims)}",
            f"**Counterexamples found:** {len(state.counterexamples)}",
            f"**Total attempts:** {len(state.attempts)}",
            "",
            "### Verified Claims",
            "",
        ])

        for claim in sorted(
            state.verified_claims, key=lambda c: c.created_at
        ):
            lines.append(f"#### {claim.id}")
            lines.append(f"- **Statement:** {claim.statement}")
            lines.append(f"- **Type:** {claim.claim_type}")
            lines.append(f"- **Strategy:** {claim.strategy_family}")
            lines.append(
                f"- **Dependencies:** {', '.join(claim.dependencies) or 'none'}"
            )
            lines.append("")

        if state.counterexamples:
            lines.extend([
                "### Counterexamples Found",
                "",
            ])
            for cx in state.counterexamples:
                lines.append(
                    f"- **Claim {cx.claim_id}:** "
                    f"{json.dumps(cx.witness_structure)} "
                    f"(method: {cx.generation_method})"
                )
            lines.append("")

        lines.extend([
            "## Version Log",
            "",
            f"**Final version:** {state.version}",
            f"**Branch:** {state.branch_id}",
            "",
        ])

        path.write_text("\n".join(lines))
        return path

    def _generate_proof_graph(self, state: ProofState) -> Path:
        """Generate proof_graph.json — dependency graph of claims."""
        path = self.output_dir / "proof_graph.json"

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []

        for claim in state.claims.values():
            nodes.append({
                "id": claim.id,
                "statement": claim.statement,
                "type": claim.claim_type,
                "status": claim.status,
                "strategy": claim.strategy_family,
            })

            for dep in claim.dependencies:
                edges.append({
                    "from": dep,
                    "to": claim.id,
                })

        graph = {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "verified_count": len(state.verified_claims),
                "total_claims": len(state.claims),
            },
        }

        path.write_text(json.dumps(graph, indent=2))
        return path

    def _generate_verification_log(self, state: ProofState) -> Path:
        """Generate verification_log.json — all verification artifacts."""
        path = self.output_dir / "verification_log.json"

        entries: list[dict[str, Any]] = []
        for claim in state.claims.values():
            for artifact in claim.verification_artifacts:
                entries.append({
                    "claim_id": claim.id,
                    "stage": artifact.stage,
                    "result": artifact.result,
                    "details": artifact.details,
                    "log_path": artifact.log_path,
                    "timestamp": artifact.timestamp,
                })

        path.write_text(json.dumps(entries, indent=2))
        return path

    def _generate_rejected_claims(self, state: ProofState) -> Path:
        """Generate rejected_claims.json — all rejected claims and reasons."""
        path = self.output_dir / "rejected_claims.json"

        rejected: list[dict[str, Any]] = []
        for claim in state.rejected_claims:
            rejected.append({
                "id": claim.id,
                "statement": claim.statement,
                "type": claim.claim_type,
                "strategy": claim.strategy_family,
                "artifacts": [
                    {
                        "stage": a.stage,
                        "result": a.result,
                        "details": a.details,
                    }
                    for a in claim.verification_artifacts
                ],
            })

        # Add attempt records
        attempts: list[dict[str, Any]] = []
        for att in state.attempts:
            attempts.append({
                "branch": att.branch_id,
                "failed_claim": att.failed_claim,
                "failure_reason": att.failure_reason,
                "verifier_stage": att.verifier_stage,
                "strategy": att.strategy_used,
                "timestamp": att.timestamp,
            })

        data = {
            "rejected_claims": rejected,
            "attempts": attempts,
        }

        path.write_text(json.dumps(data, indent=2))
        return path

    def _generate_run_manifest(
        self,
        state: ProofState,
        spec: FormalSpec,
        *,
        config_dict: dict[str, Any] | None = None,
        artifacts: dict[str, Path] | None = None,
    ) -> Path:
        """Generate run_manifest.json — full reproducibility record."""
        path = self.output_dir / "run_manifest.json"

        manifest = {
            "ampp_version": "0.1.0",
            "timestamp": datetime.now(UTC).isoformat(),
            "problem_id": spec.problem_id,
            "problem_hash": spec.hash,
            "state_hash": state.state_hash(),
            "state_version": state.version,
            "platform": {
                "system": platform.system(),
                "python_version": platform.python_version(),
                "machine": platform.machine(),
            },
            "config": config_dict or {},
            "results": {
                "verified_claims": len(state.verified_claims),
                "rejected_claims": len(state.rejected_claims),
                "counterexamples": len(state.counterexamples),
                "attempts": len(state.attempts),
                "theorem_verified": state.has_verified_theorem(),
            },
            "artifacts": {
                name: str(path)
                for name, path in (artifacts or {}).items()
            },
            "version_log_entries": len(state.version_log),
        }

        path.write_text(json.dumps(manifest, indent=2))
        return path
