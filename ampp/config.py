"""Centralised runtime configuration for AMPP.

All environment-variable reads are consolidated here so that the rest of
the codebase never calls `os.getenv` directly for configuration values.

Import pattern:
    from ampp.config import cfg

All values can be overridden in tests by setting env vars before import,
or by calling `config.override(...)`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class AMPPConfig:
    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: str = field(
        default_factory=lambda: os.getenv("AMPP_LLM_PROVIDER", "openai").lower()
    )
    openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    openai_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o")
    )
    openai_base_url: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL")
    )
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
    )
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
    )
    llm_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("AMPP_LLM_MAX_TOKENS", "2048"))
    )
    llm_temperature: float = field(
        default_factory=lambda: float(os.getenv("AMPP_LLM_TEMPERATURE", "0.2"))
    )
    llm_retries: int = field(
        default_factory=lambda: int(os.getenv("AMPP_LLM_RETRIES", "3"))
    )

    # ── Pipeline ──────────────────────────────────────────────────────────────
    max_iterations: int = field(
        default_factory=lambda: int(os.getenv("AMPP_MAX_ITERATIONS", "200"))
    )
    beam_width: int = field(
        default_factory=lambda: int(os.getenv("AMPP_BEAM_WIDTH", "4"))
    )
    stale_threshold: int = field(
        default_factory=lambda: int(os.getenv("AMPP_STALE_THRESHOLD", "10"))
    )
    random_seed: int = field(
        default_factory=lambda: int(os.getenv("AMPP_RANDOM_SEED", "42"))
    )
    max_candidates_per_proposer: int = field(
        default_factory=lambda: int(os.getenv("AMPP_MAX_CANDIDATES_PER_PROPOSER", "3"))
    )

    # ── Verifiers ─────────────────────────────────────────────────────────────
    z3_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("AMPP_Z3_TIMEOUT_MS", "30000"))
    )
    lean_timeout_sec: int = field(
        default_factory=lambda: int(os.getenv("AMPP_LEAN_TIMEOUT_SEC", "120"))
    )
    atp_timeout_sec: int = field(
        default_factory=lambda: int(os.getenv("AMPP_ATP_TIMEOUT_SEC", "30"))
    )
    v1_random_trials: int = field(
        default_factory=lambda: int(os.getenv("AMPP_V1_RANDOM_TRIALS", "500"))
    )
    v1_max_enumeration_bound: int = field(
        default_factory=lambda: int(os.getenv("AMPP_V1_MAX_ENUM_BOUND", "10000"))
    )

    # ── Rubric ────────────────────────────────────────────────────────────────
    rubric_pass_threshold: int = field(
        default_factory=lambda: int(os.getenv("AMPP_RUBRIC_PASS_THRESHOLD", "70"))
    )

    # ── Artifacts ─────────────────────────────────────────────────────────────
    output_dir: str = field(
        default_factory=lambda: os.getenv("AMPP_OUTPUT_DIR", "output")
    )
    db_path: str = field(
        default_factory=lambda: os.getenv("AMPP_DB_PATH", "ampp_state.db")
    )

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def is_openclaw(self) -> bool:
        """True when configured with a custom OpenAI-compatible base URL (e.g. OpenClaw)."""
        return bool(self.openai_base_url)

    @property
    def effective_provider(self) -> str:
        """Resolve which provider will actually be used."""
        if self.llm_provider == "anthropic" and self.has_anthropic:
            return "anthropic"
        if self.has_openai:
            return "openai"
        if self.has_anthropic:
            return "anthropic"
        return "null"


# ── Module-level singleton ────────────────────────────────────────────────────
cfg = AMPPConfig()
