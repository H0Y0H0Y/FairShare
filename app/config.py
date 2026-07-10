"""Application configuration, loaded from environment variables.

All runtime knobs live here so the rest of the code depends on a single, typed
``Settings`` object instead of reading ``os.environ`` ad hoc.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

# Load a local .env when present (no-op in the container, where env is injected).
load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class PartnerConfig:
    """One of the two fixed partners."""

    id: int  # 1 or 2
    name: str
    telegram_id: int


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str

    partners: tuple[PartnerConfig, PartnerConfig]

    openrouter_api_key: str
    openrouter_base_url: str
    vision_model: str
    text_model: str

    currency: str
    currency_symbol: str

    db_path: str
    draft_timeout: int

    # --- Derived helpers ---------------------------------------------------

    @property
    def allowed_telegram_ids(self) -> frozenset[int]:
        return frozenset(p.telegram_id for p in self.partners)

    def partner_by_telegram_id(self, telegram_id: int) -> PartnerConfig | None:
        for p in self.partners:
            if p.telegram_id == telegram_id:
                return p
        return None

    def partner_by_id(self, partner_id: int) -> PartnerConfig:
        for p in self.partners:
            if p.id == partner_id:
                return p
        raise KeyError(f"Unknown partner id: {partner_id}")

    def other_partner(self, partner_id: int) -> PartnerConfig:
        return self.partners[1] if partner_id == self.partners[0].id else self.partners[0]

    def partner_by_name(self, name: str) -> PartnerConfig | None:
        needle = name.strip().lower()
        for p in self.partners:
            if p.name.lower() == needle:
                return p
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build (once) and return the immutable Settings singleton."""
    p1 = PartnerConfig(
        id=1,
        name=_require("PARTNER_1_NAME"),
        telegram_id=int(_require("PARTNER_1_TELEGRAM_ID")),
    )
    p2 = PartnerConfig(
        id=2,
        name=_require("PARTNER_2_NAME"),
        telegram_id=int(_require("PARTNER_2_TELEGRAM_ID")),
    )
    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        partners=(p1, p2),
        openrouter_api_key=_require("OPENROUTER_API_KEY"),
        openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        vision_model=os.getenv("VISION_MODEL", "qwen/qwen-2.5-vl-72b-instruct"),
        # gpt-4o-mini: cheap, extracts splits reliably, and is served first-party
        # by OpenAI (no multi-provider routing roulette). llama-3.1-8b dropped
        # splits; qwen-2.5-72b was flaky under provider rate-limits/fallbacks.
        text_model=os.getenv("TEXT_MODEL", "openai/gpt-4o-mini"),
        currency=os.getenv("CURRENCY", "PHP"),
        currency_symbol=os.getenv("CURRENCY_SYMBOL", ""),
        db_path=os.getenv("DB_PATH", "/app/data/expenses.db"),
        draft_timeout=int(os.getenv("DRAFT_TIMEOUT", "300")),
    )
