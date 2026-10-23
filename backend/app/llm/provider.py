"""LLM provider abstraction.

Three providers ship with PromiseLoop:

* ``gemini`` - Google Gemini through its OpenAI-compatible endpoint. Configured
  with ``GEMINI_API_KEY`` / ``GEMINI_MODEL``.
* ``openai`` - any OpenAI-compatible ``/chat/completions`` endpoint (OpenAI,
  Amazon Bedrock, Groq, OpenRouter, Ollama, ...). Configured with
  ``LLM_BASE_URL`` / ``LLM_API_KEY`` / ``LLM_MODEL``.
* ``mock``   - a deterministic, offline planner. No API key, no network, and
  the same tool-calling loop, so the whole demo (including MCP) works without
  credentials.

All providers speak the same message format as the OpenAI chat API, so the
agent code never has to care which one is in use.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import get_settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    extra_content: dict[str, Any] | None = None


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ProviderError(RuntimeError):
    """Sanitized provider failure: safe to show to the user."""

    def __init__(self, status_code: int, category: str) -> None:
        super().__init__(f"LLM request failed ({status_code}): {category}")
        self.status_code = status_code
        self.category = category


class LLMProvider(Protocol):
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse: ...

    async def structured(
        self, messages: list[dict[str, Any]], schema: dict[str, Any], name: str = "result"
    ) -> dict[str, Any]: ...


class OpenAICompatibleProvider:
    """Talks to any OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        timeout: float = 45.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        retryable = {429, 500, 502, 503, 504}
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise ProviderError(0, "network/timeout") from exc
            else:
                if response.status_code < 400:
                    return response.json()
                if response.status_code not in retryable or attempt == 2:
                    raise ProviderError(
                        response.status_code, _error_category(response.status_code)
                    )
            await asyncio.sleep(0.8 * (attempt + 1))
        raise ProviderError(0, "network/timeout")

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = await self._post(payload)
        message = (data.get("choices") or [{}])[0].get("message") or {}
        calls = [
            ToolCall(
                id=call.get("id", f"call_{index}"),
                name=(call.get("function") or {}).get("name", ""),
                arguments=_safe_json((call.get("function") or {}).get("arguments")),
                extra_content=call.get("extra_content")
                if isinstance(call.get("extra_content"), dict)
                else None,
            )
            for index, call in enumerate(message.get("tool_calls") or [])
        ]
        return LLMResponse(content=message.get("content"), tool_calls=calls)

    async def structured(
        self, messages: list[dict[str, Any]], schema: dict[str, Any], name: str = "result"
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "schema": schema, "strict": True},
            },
        }
        try:
            data = await self._post(payload)
        except ProviderError as exc:
            if exc.status_code not in {400, 404, 422}:
                raise
            # Endpoints without json_schema support still accept json_object.
            payload["response_format"] = {"type": "json_object"}
            data = await self._post(payload)

        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or "{}"
        return json.loads(content)


def _error_category(status_code: int) -> str:
    if status_code in (401, 403):
        return "authentication/configuration"
    if status_code == 404:
        return "model or endpoint not found"
    if status_code == 429:
        return "rate limit or quota"
    if status_code >= 500:
        return "provider unavailable"
    return "request rejected"


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_provider() -> LLMProvider:
    """Return the explicitly configured provider.

    An unknown provider name is an error, never a silent fallback to mock.
    """
    settings = get_settings()
    name = settings.llm_provider.strip().lower()

    if name == "gemini":
        api_key = settings.gemini_api_key or settings.llm_api_key
        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY (or LLM_API_KEY) is not set"
            )
        return OpenAICompatibleProvider(
            base_url=settings.gemini_base_url,
            api_key=api_key,
            model=settings.gemini_model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
        )

    if name == "openai":
        return OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
        )

    if name in {"mock", ""}:
        from app.llm.mock import MockProvider

        return MockProvider()

    raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")
