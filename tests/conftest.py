"""Shared test setup: inject a minimal environment so ``get_settings()`` works,
and expose partner configs for building drafts."""
from __future__ import annotations

import os

# Populate required env BEFORE any app module reads it.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("PARTNER_1_NAME", "Mark")
os.environ.setdefault("PARTNER_1_TELEGRAM_ID", "111")
os.environ.setdefault("PARTNER_2_NAME", "Alex")
os.environ.setdefault("PARTNER_2_TELEGRAM_ID", "222")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("CURRENCY", "PHP")
os.environ.setdefault("CURRENCY_SYMBOL", "")
os.environ.setdefault("DB_PATH", ":memory:")

import pytest

from app.config import Settings, get_settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
