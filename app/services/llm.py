"""Model-agnostic LLM backend for ServiceSync.

The application code (triage, dispute analysis, price estimation, contractor
auto-reply) should never depend on a single vendor. This module exposes one
`complete()` call and a `get_provider()` factory so the active model can be
swapped at deploy time via ``AI_PROVIDER`` without touching any prompt logic:

    gemini  -> Google Gemini (default; best reasoning, free tier available)
    groq    -> Groq OpenAI-compatible API (Llama/Mixtral; fast + free tier)
    ollama  -> local Ollama server (fully offline, zero per-call cost)

Why this matters: it removes lock-in to a paid API and gives a clear path to
self-hosted inference later. See the CALL-E / ServiceSync Voice architecture.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("services.llm")


class BaseLLMProvider:
    name: str = "base"

    async def complete(self, prompt: str, *, json_mode: bool = False, temperature: float = 0.4) -> str:
        raise NotImplementedError


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None
        self._model = settings.GEMINI_MODEL

    async def complete(self, prompt: str, *, json_mode: bool = False, temperature: float = 0.4) -> str:
        if self._client is None:
            raise RuntimeError("Gemini is not configured (no GEMINI_API_KEY)")
        config = self._types.GenerateContentConfig(temperature=temperature)
        if json_mode:
            config.response_mime_type = "application/json"
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=prompt, config=config
        )
        return response.text or ""


class GroqProvider(BaseLLMProvider):
    name = "groq"

    def __init__(self) -> None:
        self._api_key = settings.GROQ_API_KEY
        self._model = settings.GROQ_MODEL
        self._url = "https://api.groq.com/openai/v1/chat/completions"

    async def complete(self, prompt: str, *, json_mode: bool = False, temperature: float = 0.4) -> str:
        if not self._api_key:
            raise RuntimeError("Groq is not configured (no GROQ_API_KEY)")
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


class OllamaProvider(BaseLLMProvider):
    name = "ollama"

    def __init__(self) -> None:
        self._base = settings.OLLAMA_BASE_URL or "http://localhost:11434"
        self._model = settings.OLLAMA_MODEL or "qwen2.5:7b"

    async def complete(self, prompt: str, *, json_mode: bool = False, temperature: float = 0.4) -> str:
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            body["format"] = "json"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self._base}/api/chat", json=body)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")


_PROVIDERS: dict[str, BaseLLMProvider] = {}


def get_provider() -> BaseLLMProvider:
    """Return the configured LLM provider (cached per process)."""
    name = (settings.AI_PROVIDER or "gemini").lower()
    if name in _PROVIDERS:
        return _PROVIDERS[name]
    cls = {
        "gemini": GeminiProvider,
        "groq": GroqProvider,
        "ollama": OllamaProvider,
    }.get(name, GeminiProvider)
    provider = cls()
    _PROVIDERS[name] = provider
    return provider


def available_providers() -> list[str]:
    return ["gemini", "groq", "ollama"]
