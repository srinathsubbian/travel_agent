"""Thin LLM layer: any OpenAI-compatible endpoint (including your own), Anthropic, or neither."""
from __future__ import annotations

from .config import Settings


def llm_enabled(s: Settings) -> bool:
    if s.llm_provider == "openai":
        return bool(s.openai_api_key or s.openai_base_url)  # local servers often need no key
    return bool(s.anthropic_api_key)


def key_hint(s: Settings) -> str:
    if s.llm_provider == "openai":
        return "OPENAI_BASE_URL (your endpoint) or OPENAI_API_KEY"
    return "ANTHROPIC_API_KEY"


def openai_client(s: Settings):
    from openai import OpenAI

    return OpenAI(api_key=s.openai_api_key or "not-needed", base_url=s.openai_base_url or None)


def token_arg(s: Settings, n: int) -> dict:
    """Official OpenAI wants max_completion_tokens; most self-hosted servers expect max_tokens."""
    return {"max_tokens": n} if s.openai_base_url else {"max_completion_tokens": n}


def generate_text(s: Settings, system: str, user: str, max_tokens: int = 400) -> str:
    """One-shot completion. Raises on any provider error (callers decide the fallback)."""
    if s.llm_provider == "openai":
        r = openai_client(s).chat.completions.create(
            model=s.openai_model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            **token_arg(s, max_tokens))
        return (r.choices[0].message.content or "").strip()
    import anthropic

    r = anthropic.Anthropic(api_key=s.anthropic_api_key).messages.create(
        model=s.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in r.content if b.type == "text").strip()
