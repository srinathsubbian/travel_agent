"""Runtime settings, read from environment variables (and .env if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # optional convenience
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


@dataclass(frozen=True)
class Settings:
    llm_provider: str  # "openai" or "anthropic"
    openai_api_key: str
    openai_model: str
    openai_base_url: str  # any OpenAI-compatible endpoint (vLLM, Ollama, LM Studio, LiteLLM, gateways)
    llm_tools: str  # "auto" (try tool calling, fall back), "on", or "off" (JSON extraction mode)
    anthropic_api_key: str
    model: str  # Anthropic model name
    data_provider: str
    amadeus_client_id: str
    amadeus_client_secret: str
    amadeus_base_url: str
    feedback_file: str


def get_settings() -> Settings:
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    default_provider = "openai" if openai_key or base_url or not anthropic_key else "anthropic"
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", default_provider).lower(),
        openai_api_key=openai_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_base_url=base_url,
        llm_tools=os.getenv("LLM_TOOLS", "auto").lower(),
        anthropic_api_key=anthropic_key,
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        data_provider=os.getenv("DATA_PROVIDER", "synthetic").lower(),
        amadeus_client_id=os.getenv("AMADEUS_CLIENT_ID", ""),
        amadeus_client_secret=os.getenv("AMADEUS_CLIENT_SECRET", ""),
        amadeus_base_url=os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com"),
        feedback_file=os.getenv("FEEDBACK_FILE", "data/feedback.jsonl"),
    )
