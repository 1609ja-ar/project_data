"""Minimal OpenAI-compatible Chat Completions client over httpx (used for Groq and xAI)."""
from __future__ import annotations

import logging

import httpx

from app.ai.base import AIError, ChatMessage

log = logging.getLogger("app.ai")


class OpenAICompatibleClient:
    def __init__(self, name: str, base_url: str, api_key: str, model: str, timeout: float,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.name = name
        self.model = model
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout
        self._transport = transport

    async def chat(self, messages: list[ChatMessage], *, temperature: float = 0.1, max_tokens: int = 800) -> str:
        body = {"model": self.model, "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": temperature, "max_tokens": max_tokens, "stream": False}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                r = await client.post(f"{self._base}/chat/completions", json=body,
                                      headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"})
        except httpx.TimeoutException:
            raise AIError(f"{self.name} did not respond in time. Try again.", "ai_timeout")
        except httpx.HTTPError:
            raise AIError(f"Could not reach {self.name}. Check the server's network connection.", "ai_unreachable")
        if r.status_code in (401, 403):
            log.error("AI provider %s rejected the API key (status %s)", self.name, r.status_code)
            raise AIError(f"{self.name} rejected the server's API key. Ask the administrator to check it.", "ai_auth")
        if r.status_code == 429:
            raise AIError(f"{self.name} rate limit reached. Wait a moment and try again.", "ai_rate_limited")
        if r.status_code == 404 and "model_not_found" in r.text:
            log.error("AI provider %s does not offer model %s: %s", self.name, self.model, r.text[:300])
            raise AIError(f"{self.name} does not offer the model '{self.model}' (it may have been retired). "
                          "Ask the administrator to update the model setting.", "ai_error")
        if r.status_code >= 400:
            log.error("AI provider %s error status=%s body=%s", self.name, r.status_code, r.text[:300])
            raise AIError(f"{self.name} returned an error ({r.status_code}).", "ai_error")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise AIError(f"{self.name} returned an unexpected response.", "ai_error")
