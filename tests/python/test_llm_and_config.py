"""Tests for ampp.llm and ampp.config."""
from __future__ import annotations

import pytest


# ── Config tests ──────────────────────────────────────────────────────────────

class TestAMPPConfig:
    def test_defaults(self):
        from ampp.config import AMPPConfig
        cfg = AMPPConfig()
        assert cfg.openai_model == "gpt-4o"
        assert cfg.anthropic_model == "claude-opus-4-5"
        assert cfg.llm_max_tokens == 2048
        assert cfg.beam_width == 4

    def test_module_singleton(self):
        from ampp.config import cfg as a
        from ampp.config import cfg as b
        assert a is b

    def test_env_override_openai_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "gpt-3.5-turbo")
        from ampp.config import AMPPConfig
        c = AMPPConfig()
        assert c.openai_model == "gpt-3.5-turbo"

    def test_env_override_max_tokens(self, monkeypatch):
        monkeypatch.setenv("AMPP_LLM_MAX_TOKENS", "512")
        from ampp.config import AMPPConfig
        c = AMPPConfig()
        assert c.llm_max_tokens == 512

    def test_openai_base_url_for_openclaw(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://openclaw.example.com/v1")
        from ampp.config import AMPPConfig
        c = AMPPConfig()
        assert c.openai_base_url == "https://openclaw.example.com/v1"
        assert c.is_openclaw is True

    def test_effective_provider_null_when_no_keys(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("AMPP_LLM_PROVIDER", "openai")
        from ampp.config import AMPPConfig
        c = AMPPConfig()
        assert c.effective_provider == "null"

    def test_effective_provider_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from ampp.config import AMPPConfig
        c = AMPPConfig()
        assert c.effective_provider == "openai"

    def test_effective_provider_anthropic_explicit(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        monkeypatch.setenv("AMPP_LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from ampp.config import AMPPConfig
        c = AMPPConfig()
        assert c.effective_provider == "anthropic"

    def test_has_openai_false_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from ampp.config import AMPPConfig
        c = AMPPConfig()
        assert c.has_openai is False

    def test_has_anthropic_false_without_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from ampp.config import AMPPConfig
        c = AMPPConfig()
        assert c.has_anthropic is False


# ── LLM provider tests ────────────────────────────────────────────────────────

class TestLLMProvider:
    def test_get_provider_returns_provider(self):
        from ampp.llm import get_provider, LLMProvider
        provider = get_provider()
        assert isinstance(provider, LLMProvider)

    def test_null_provider_returns_empty_string(self):
        from ampp.llm import NullProvider
        p = NullProvider()
        result = p.complete("sys", "user")
        assert result == ""

    def test_null_provider_complete_json_returns_none(self):
        from ampp.llm import NullProvider
        p = NullProvider()
        result = p.complete_json("sys", "user")
        assert result is None

    def test_set_provider_overrides_global(self):
        from ampp.llm import get_provider, set_provider, NullProvider
        null = NullProvider()
        set_provider(null)
        try:
            assert get_provider() is null
        finally:
            set_provider(None)

    def test_set_provider_none_restores_env_detection(self, monkeypatch):
        from ampp.llm import set_provider, get_provider, NullProvider
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("AMPP_LLM_PROVIDER", raising=False)
        set_provider(NullProvider())
        set_provider(None)  # clear override
        p = get_provider()
        assert isinstance(p, NullProvider)

    def test_get_provider_null_when_no_keys(self, monkeypatch):
        from ampp.llm import set_provider, get_provider, NullProvider
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("AMPP_LLM_PROVIDER", raising=False)
        set_provider(None)  # ensure no override
        try:
            p = get_provider()
            assert isinstance(p, NullProvider)
        finally:
            set_provider(None)

    def test_llm_generate_claims_returns_list(self):
        from ampp.llm import llm_generate_claims
        result = llm_generate_claims("system", "user")
        assert isinstance(result, list)

    def test_llm_generate_claims_empty_with_null_provider(self):
        from ampp.llm import llm_generate_claims, set_provider, NullProvider
        set_provider(NullProvider())
        try:
            result = llm_generate_claims("system", "user")
            assert result == []
        finally:
            set_provider(None)

    def test_complete_json_returns_none_on_empty(self):
        """NullProvider always returns '' — complete_json returns None."""
        from ampp.llm import NullProvider
        p = NullProvider()
        assert p.complete_json("sys", "user") is None

    def test_complete_json_strips_markdown_fences(self):
        """complete_json should strip ```json ... ``` wrappers."""
        from ampp.llm import LLMProvider

        class FakeProvider(LLMProvider):
            def complete(self, system, user, **kwargs) -> str:
                return '```json\n{"claims": ["foo"]}\n```'

        p = FakeProvider()
        result = p.complete_json("sys", "user")
        assert result is not None
        assert result.get("claims") == ["foo"]

    def test_provider_detection_anthropic_env(self, monkeypatch):
        from ampp.llm import set_provider, get_provider, AnthropicProvider
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        monkeypatch.setenv("AMPP_LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        set_provider(None)
        try:
            p = get_provider()
            assert isinstance(p, AnthropicProvider)
        finally:
            set_provider(None)

    def test_provider_detection_openai_env(self, monkeypatch):
        from ampp.llm import set_provider, get_provider, OpenAIProvider
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("AMPP_LLM_PROVIDER", raising=False)
        set_provider(None)
        try:
            p = get_provider()
            assert isinstance(p, OpenAIProvider)
        finally:
            set_provider(None)
