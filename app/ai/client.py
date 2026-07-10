"""OpenRouter-backed chat client (singleton).

OpenRouter exposes the OpenAI-compatible ``/chat/completions`` API (verified: it
does NOT implement the Anthropic Messages API for third-party models such as
Qwen/Llama), so we use the OpenAI SDK with ``base_url`` pointed at OpenRouter.

All AI access is funneled through this one module, so switching providers or SDKs
is a change confined to this file plus ``parser.py``.
"""
from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import get_settings


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
    )
