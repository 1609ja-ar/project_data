"""Chooses the AI provider for a user: their choice if configured, else the server default."""
from __future__ import annotations

import re

from app.ai.base import AIError, AIProvider
from app.ai.grok_service import grok_client
from app.ai.groq_service import groq_client
from app.core.config import get_settings

_transport_override = None  # tests inject an httpx.MockTransport here


def set_test_transport(transport) -> None:
    global _transport_override
    _transport_override = transport


def get_provider(user: dict) -> AIProvider:
    s = get_settings()
    configured = s.configured_ai_providers()
    if not configured:
        raise AIError("No AI provider is configured on this server. Everything else works without AI.", "ai_not_configured")
    choice = user.get("ai_provider") if user.get("ai_provider") in configured else (
        s.ai_provider if s.ai_provider in configured else configured[0])
    return groq_client(s, _transport_override) if choice == "groq" else grok_client(s, _transport_override)


_NUMBER_RE = re.compile(r"(?<![\w.])[-−]?\$?€?£?₹?\d[\d,]*(?:\.\d+)?%?")


def extract_numbers(text: str) -> list[str]:
    return _NUMBER_RE.findall(text)


def check_numbers(text: str, allowed: list[float], rel: float = 0.005) -> tuple[str, list[str]]:
    """Accuracy rule 8: every number in AI text must appear in the result payload (within rounding).

    Unmatched numbers are marked "[unverified]" and returned so the caller can log the event.
    Small integers 0-10 (list markers, "top 3") and 4-digit years are allowed.
    """
    def parse(tok: str):
        t = tok.replace("−", "-").replace(",", "").strip("$€£₹")
        pct = t.endswith("%")
        t = t.rstrip("%")
        try:
            v = float(t)
        except ValueError:
            return None, pct
        return v, pct

    def ok(v: float, pct: bool) -> bool:
        if v == int(v) and (0 <= abs(v) <= 10 or 1900 <= v <= 2100):
            return True
        cands = [v / 100] if pct else []
        cands.append(v)
        for c in cands:
            for a in allowed:
                if a is None:
                    continue
                tol = max(abs(a) * rel, 0.006 if abs(a) < 100 else 0.51)
                if abs(c - a) <= tol or (pct and abs(c * 100 - a * 100) <= 0.051):
                    return True
        return False

    bad: list[str] = []

    def repl(m: re.Match) -> str:
        tok = m.group(0)
        v, pct = parse(tok)
        if v is None or ok(v, pct):
            return tok
        bad.append(tok)
        return f"{tok} [unverified]"

    return _NUMBER_RE.sub(repl, text), bad
