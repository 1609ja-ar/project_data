from app.ai.openai_compatible import OpenAICompatibleClient
from app.core.config import Settings


def groq_client(s: Settings, transport=None) -> OpenAICompatibleClient:
    """Groq (groq.com), keys start with gsk_. OpenAI-compatible base URL: https://api.groq.com/openai/v1"""
    return OpenAICompatibleClient("Groq", s.groq_base_url, s.groq_api_key, s.groq_model, s.ai_timeout_seconds, transport)
