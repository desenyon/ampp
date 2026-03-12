"""LLM Provider abstraction for AMPP.

Supports:
  • OpenAI (default) — including OpenClaw via OPENAI_BASE_URL
  • Anthropic

Priority (first configured wins):
  1. If AMPP_LLM_PROVIDER=anthropic → Anthropic
  2. If OPENAI_API_KEY present       → OpenAI / OpenClaw
  3. If ANTHROPIC_API_KEY present    → Anthropic
  4. No key → graceful degradation (returns empty proposals)

OpenClaw / custom-base-URL:
  Set OPENAI_BASE_URL to your OpenClaw endpoint.  The OpenAI client picks
  this up automatically via the environment; no code change needed.

Environment variables
─────────────────────
  AMPP_LLM_PROVIDER   "openai" | "anthropic"  (optional override)
  OPENAI_API_KEY      required for OpenAI / OpenClaw
  OPENAI_BASE_URL     optional custom base URL  (OpenClaw, Azure, etc.)
  OPENAI_MODEL        default "gpt-4o"
  ANTHROPIC_API_KEY   required for Anthropic
  ANTHROPIC_MODEL     default "claude-opus-4-5"
  AMPP_LLM_MAX_TOKENS default 2048
  AMPP_LLM_TEMPERATURE default 0.2
  AMPP_LLM_RETRIES    default 3
"""
from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-5"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.2
DEFAULT_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds


# ── Abstract base ─────────────────────────────────────────────────────────────

class LLMProvider(ABC):
    """Abstract LLM provider.  All providers share the same interface."""

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        """Return the raw completion text."""

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> dict[str, Any] | None:
        """Return parsed JSON from the completion, or None on failure."""
        text = self.complete(system, user, max_tokens=max_tokens, temperature=temperature)
        if not text:
            return None
        # Strip markdown code fences if present
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            # Last-chance: find first { ... } block
            start = stripped.find("{")
            end = stripped.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(stripped[start:end])
                except json.JSONDecodeError:
                    pass
        logger.debug("complete_json: could not parse JSON from response")
        return None

    # ── Retry wrapper ─────────────────────────────────────────────────────────

    def _with_retry(self, fn: Any, retries: int, *args: Any, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                wait = _BACKOFF_BASE ** attempt
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1,
                    retries,
                    exc,
                    wait,
                )
                time.sleep(wait)
        logger.error("LLM call exhausted retries: %s", last_exc)
        raise RuntimeError(f"LLM call failed after {retries} retries") from last_exc


# ── OpenAI / OpenClaw provider ────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    """OpenAI provider.  Also works with OpenClaw and any OpenAI-compatible API.

    If OPENAI_BASE_URL is set the client uses that endpoint (e.g. OpenClaw,
    Azure OpenAI, local vLLM, etc.).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self._api_key = api_key or os.environ["OPENAI_API_KEY"]
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        self._base_url = base_url or os.getenv("OPENAI_BASE_URL")  # None = default
        self._retries = retries
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
                logger.info("OpenAI client using custom base_url: %s", self._base_url)
            self._client = openai.OpenAI(**kwargs)
        return self._client

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        def _call() -> str:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""

        try:
            return self._with_retry(_call, self._retries)
        except Exception as exc:
            logger.warning("OpenAI complete failed: %s", exc)
            return ""

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_openclaw(self) -> bool:
        return self._base_url is not None


# ── Anthropic provider ────────────────────────────────────────────────────────

class AnthropicProvider(LLMProvider):
    """Anthropic (Claude) provider."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self._api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self._model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
        self._retries = retries
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        def _call() -> str:
            client = self._get_client()
            message = client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text_block = next(
                (b for b in message.content if b.type == "text"), None
            )
            return text_block.text if text_block is not None else ""

        try:
            return self._with_retry(_call, self._retries)
        except Exception as exc:
            logger.warning("Anthropic complete failed: %s", exc)
            return ""

    @property
    def model(self) -> str:
        return self._model


# ── Null / fallback provider ──────────────────────────────────────────────────

class NullProvider(LLMProvider):
    """Returns empty results when no API key is available.  Keeps tests runnable."""

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        logger.debug("NullProvider.complete() — no LLM configured")
        return ""


# ── Registry / factory ────────────────────────────────────────────────────────

_PROVIDER_OVERRIDE: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """Return the active LLMProvider singleton.

    Resolution order
    ────────────────
    1. Global override set by ``set_provider()`` (useful for testing)
    2. AMPP_LLM_PROVIDER env var
    3. OPENAI_API_KEY present → OpenAI / OpenClaw
    4. ANTHROPIC_API_KEY present → Anthropic
    5. NullProvider (no keys found)
    """
    global _PROVIDER_OVERRIDE
    if _PROVIDER_OVERRIDE is not None:
        return _PROVIDER_OVERRIDE

    explicit = os.getenv("AMPP_LLM_PROVIDER", "").lower()
    if explicit == "anthropic":
        if os.getenv("ANTHROPIC_API_KEY"):
            return AnthropicProvider()
        logger.warning("AMPP_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY not set")

    if explicit == "openai" or os.getenv("OPENAI_API_KEY"):
        if os.getenv("OPENAI_API_KEY"):
            return OpenAIProvider()
        logger.warning("AMPP_LLM_PROVIDER=openai but OPENAI_API_KEY not set")

    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicProvider()

    logger.debug("No LLM API key configured — using NullProvider")
    return NullProvider()


def set_provider(provider: LLMProvider | None) -> None:
    """Override the global LLM provider (e.g. for testing or CLI flags)."""
    global _PROVIDER_OVERRIDE
    _PROVIDER_OVERRIDE = provider


# ── Convenience wrapper ───────────────────────────────────────────────────────

def llm_generate_claims(
    system_prompt: str,
    user_prompt: str,
    *,
    max_claims: int = 5,
) -> list[str]:
    """Call the active LLM and return a list of claim strings.

    The LLM is instructed to respond with JSON:
      {"claims": ["<claim 1>", "<claim 2>", ...]}

    Falls back to an empty list on any failure so the pipeline degrades
    gracefully without API keys.
    """
    provider = get_provider()
    if isinstance(provider, NullProvider):
        return []

    json_instruction = (
        "\n\nRespond ONLY with a JSON object — no prose, no markdown.\n"
        'Format: {"claims": ["<claim statement 1>", "<claim statement 2>", ...]}\n'
        f"Include at most {max_claims} claims.  Each claim must be a single, concrete, "
        "machine-verifiable mathematical statement."
    )

    result = provider.complete_json(system_prompt + json_instruction, user_prompt)
    if result is None:
        return []

    claims = result.get("claims", [])
    if not isinstance(claims, list):
        return []
    return [str(c).strip() for c in claims if str(c).strip()][:max_claims]
