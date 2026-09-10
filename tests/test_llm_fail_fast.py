"""LLM configuration fail-fast tests.

Silent mock fallback made a misconfigured production deployment look like a
working model. Mock completions are now gated on APP_ENV=test/dev + MOCK_LLM=true;
production must fail fast with a configuration error.
"""

import asyncio

import pytest

from backend.agent.llm import LLMClient, LLMConfigurationError
from backend.config import settings


def test_missing_api_key_fails_fast_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "mock_llm", False)
    client = LLMClient(api_key="")

    with pytest.raises(LLMConfigurationError):
        asyncio.run(client.chat_completion([{"role": "user", "content": "hi"}]))


def test_dummy_mock_key_is_rejected_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "mock_llm", True)
    client = LLMClient(api_key="mock_not_real")

    with pytest.raises(LLMConfigurationError):
        asyncio.run(client.chat_completion([{"role": "user", "content": "hi"}]))


def test_mock_fallback_allowed_in_explicit_test_mode(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "mock_llm", True)
    client = LLMClient(api_key="")

    response = asyncio.run(client.chat_completion([{"role": "user", "content": "hi"}]))
    assert response["choices"][0]["message"]["content"]


def test_stream_fails_fast_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "mock_llm", False)
    client = LLMClient(api_key="")

    async def _consume():
        async for _ in client.chat_stream([{"role": "user", "content": "hi"}]):
            pass

    with pytest.raises(LLMConfigurationError):
        asyncio.run(_consume())
