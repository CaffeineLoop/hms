"""OpenRouter provider (Ling Sante via OpenRouter) in the existing Stage 7 provider registry.

Offline only: models are constructed, never called. The live request is a separate manual check.
"""

import re
from pathlib import Path

import pytest

from app.ai.providers import PROVIDERS, AIUnavailableError, build_model_factory, model_is_configured
from app.core.config import LLM_PROVIDERS, load_settings

LING = "inclusionai/ling-3.0-flash-sante:free"
FAKE_KEY = "sk-or-test-key-not-real-0000"


def settings(monkeypatch, **env):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://hms_app:change-me@127.0.0.1:1/hms_dev")
    for key in ("LLM_PROVIDER", "LLM_MODEL", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return load_settings(_env_file=None)


def test_config_allowlist_matches_the_provider_registry():
    assert set(PROVIDERS) == set(LLM_PROVIDERS) == {"gemini", "openrouter", "fake", "disabled"}


def test_openrouter_is_configured_from_the_environment(monkeypatch):
    s = settings(monkeypatch, LLM_PROVIDER="openrouter", LLM_MODEL=LING, OPENROUTER_API_KEY=FAKE_KEY)
    assert (s.llm_provider, s.llm_model, s.openrouter_base_url) == ("openrouter", LING, "https://openrouter.ai/api/v1")
    assert FAKE_KEY not in repr(s) and FAKE_KEY not in str(s.model_dump())
    custom = settings(monkeypatch, LLM_PROVIDER="openrouter", OPENROUTER_BASE_URL="https://proxy.example.org/v1/")
    assert custom.openrouter_base_url == "https://proxy.example.org/v1"
    with pytest.raises(Exception, match="OPENROUTER_BASE_URL"):
        settings(monkeypatch, OPENROUTER_BASE_URL="http://openrouter.ai/api/v1")  # plain http refused


def test_openrouter_requires_a_key(monkeypatch):
    s = settings(monkeypatch, LLM_PROVIDER="openrouter", LLM_MODEL=LING)
    assert not model_is_configured(s)
    with pytest.raises(AIUnavailableError, match="OPENROUTER_API_KEY"):
        build_model_factory(s)()
    blank = settings(monkeypatch, LLM_PROVIDER="openrouter", OPENROUTER_API_KEY="   ")
    assert not model_is_configured(blank)


def test_openrouter_model_is_built_from_settings_without_network(monkeypatch):
    s = settings(monkeypatch, LLM_PROVIDER="openrouter", LLM_MODEL=LING, OPENROUTER_API_KEY=FAKE_KEY)
    model = build_model_factory(s)()  # constructed only; no request is sent
    assert type(model).__name__ == "ChatOpenAI"
    assert model.model_name == LING and model.openai_api_base == "https://openrouter.ai/api/v1"
    assert model.temperature == s.llm_temperature and model.max_tokens == s.llm_max_output_tokens
    assert model.max_retries == 1 and model.request_timeout == s.llm_timeout_seconds
    assert FAKE_KEY not in repr(model)
    # No provider-side JSON/schema mode is requested: Ling Sante does not support it, and the application's own
    # parsing + schema + grounding + semantic validation stay the only authority on output safety.
    assert not model.model_kwargs.get("response_format") and "response_format" not in (model.extra_body or {})
    assert model_is_configured(s)


def test_model_id_is_configuration_not_code(monkeypatch):
    s = settings(monkeypatch, LLM_PROVIDER="openrouter", LLM_MODEL="some-vendor/another-model", OPENROUTER_API_KEY=FAKE_KEY)
    assert build_model_factory(s)().model_name == "some-vendor/another-model"


SHARED_AI_MODULES = ("app/ai/graph.py", "app/ai/guardrails.py", "app/ai/grounding.py", "app/ai/prompts.py",
                     "app/ai/tools.py", "app/ai/schemas.py", "app/ai/risk_signals.py", "app/services/ai_service.py",
                     "app/api/routes/ai.py", "app/api/ai_triggers.py", "app/repositories/ai_evidence_repository.py",
                     "app/repositories/ai_risk_repository.py", "app/models/ai_review.py")


def test_shared_ai_architecture_has_no_provider_specific_assumptions():
    root = Path(__file__).resolve().parent.parent.parent
    vendor = re.compile(r"gemini|google|openrouter|openai|ling-3|\bling\b", re.I)
    offenders = [f"{m}: {line.strip()[:80]}" for m in SHARED_AI_MODULES
                 for line in (root / m).read_text(encoding="utf-8").splitlines() if vendor.search(line)]
    assert offenders == []
