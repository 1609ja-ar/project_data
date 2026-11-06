from app.ai.openai_compatible import OpenAICompatibleClient
from app.core.config import Settings


def grok_client(s: Settings, transport=None) -> OpenAICompatibleClient:
    """xAI Grok (x.ai). Base URL https://api.x.ai/v1; /chat/completions is OpenAI-compatible (xAI calls it legacy)."""
    return OpenAICompatibleClient("xAI Grok", s.xai_base_url, s.xai_api_key, s.xai_model, s.ai_timeout_seconds, transport)
