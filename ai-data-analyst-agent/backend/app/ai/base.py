"""AI provider interface. AI only writes or explains text; it never computes numbers shown to users."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class AIError(Exception):
    def __init__(self, message: str, code: str = "ai_error"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


class AIProvider(Protocol):
    name: str
    model: str

    async def chat(self, messages: list[ChatMessage], *, temperature: float = 0.1, max_tokens: int = 800) -> str: ...
