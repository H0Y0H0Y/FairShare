"""Tests for the pure rendering helpers in ``app.bot.views``."""
from __future__ import annotations

from app.bot.views import mention
from app.config import PartnerConfig


def test_mention_links_the_telegram_id() -> None:
    partner = PartnerConfig(id=1, name="Mark", telegram_id=111)
    assert mention(partner) == '<a href="tg://user?id=111">Mark</a>'


def test_mention_escapes_the_partner_name() -> None:
    partner = PartnerConfig(id=2, name="Alex & <Co>", telegram_id=222)
    assert mention(partner) == '<a href="tg://user?id=222">Alex &amp; &lt;Co&gt;</a>'
