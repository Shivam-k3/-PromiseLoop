"""Provider selection must be explicit; Gemini is not a silent mock fallback."""

import pytest

from app.config import get_settings
from app.llm.mock import MockProvider
from app.llm.provider import OpenAICompatibleProvider, build_provider


async def test_gemini_tool_metadata_is_preserved(monkeypatch):
    provider = OpenAICompatibleProvider("https://gemini.test", "key", "model")

    async def fake_post(payload):
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "list_commitments", "arguments": "{}"},
                                "extra_content": {
                                    "google": {"thought_signature": "signature"}
                                },
                            }
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    response = await provider.chat([{"role": "user", "content": "hello"}])
    assert response.tool_calls[0].extra_content == {
        "google": {"thought_signature": "signature"}
    }


def _clear_settings():
    get_settings.cache_clear()


def test_gemini_provider_uses_its_own_key_and_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://gemini.test/v1beta/openai")
    monkeypatch.setenv("LLM_API_KEY", "")
    _clear_settings()
    try:
        provider = build_provider()
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://gemini.test/v1beta/openai"
        assert provider.model == "gemini-test-model"
        assert provider.api_key == "test-gemini-key"
    finally:
        _clear_settings()


def test_gemini_without_a_key_is_an_explicit_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    _clear_settings()
    try:
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            build_provider()
    finally:
        _clear_settings()


def test_unknown_provider_is_not_silently_mocked(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "banana")
    _clear_settings()
    try:
        with pytest.raises(RuntimeError, match="Unknown LLM_PROVIDER"):
            build_provider()
    finally:
        _clear_settings()


def test_mock_provider_stays_available(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    _clear_settings()
    try:
        assert isinstance(build_provider(), MockProvider)
    finally:
        _clear_settings()
