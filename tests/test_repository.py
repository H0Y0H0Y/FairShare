import pytest

from app.config import PartnerConfig, Settings
from app.db import repository
from app.db.database import Database
from app.models import ExpenseDraft

pytestmark = pytest.mark.asyncio


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="t",
        partners=(
            PartnerConfig(id=1, name="Mark", telegram_id=111),
            PartnerConfig(id=2, name="Alex", telegram_id=222),
        ),
        openrouter_api_key="k",
        openrouter_base_url="https://openrouter.ai/api/v1",
        vision_model="v",
        text_model="t",
        currency="PHP",
        currency_symbol="",
        db_path=":memory:",
        draft_timeout=300,
    )


async def _fresh_db() -> Database:
    db = Database(_settings())
    await db.connect()
    return db


def _draft(total, paid_by, s1, s2) -> ExpenseDraft:
    return ExpenseDraft(
        description="test",
        total_cents=total,
        paid_by=paid_by,
        expense_date="2026-07-10",
        shares={1: s1, 2: s2},
    )


async def test_insert_and_balance():
    db = await _fresh_db()
    try:
        # Mark pays 700; split 500/200. Alex owes Mark 200.
        await repository.insert_expense_with_shares(db.conn, _draft(70000, 1, 50000, 20000), 111)
        bal = await repository.get_open_balance(db.conn, 1, 2)
        assert bal.net_cents == 20000
        assert bal.creditor_id == 1
        assert bal.debtor_id == 2
        assert bal.magnitude_cents == 20000
    finally:
        await db.close()


async def test_balance_nets_across_expenses():
    db = await _fresh_db()
    try:
        await repository.insert_expense_with_shares(db.conn, _draft(70000, 1, 50000, 20000), 111)
        # Alex pays 300, even split. Nets Mark's credit down to 50.
        await repository.insert_expense_with_shares(db.conn, _draft(30000, 2, 15000, 15000), 222)
        bal = await repository.get_open_balance(db.conn, 1, 2)
        assert bal.net_cents == 5000  # Mark still owed 50
        assert bal.creditor_id == 1
    finally:
        await db.close()


async def test_settle_resets_balance():
    db = await _fresh_db()
    try:
        await repository.insert_expense_with_shares(db.conn, _draft(70000, 1, 50000, 20000), 111)
        assert await repository.count_open(db.conn) == 1

        settled, sid = await repository.settle(db.conn, 1, 2)
        assert settled.magnitude_cents == 20000
        assert sid == 1

        assert await repository.count_open(db.conn) == 0
        bal = await repository.get_open_balance(db.conn, 1, 2)
        assert bal.net_cents == 0
        assert bal.creditor_id is None

        # A new expense after settling starts a fresh tally.
        await repository.insert_expense_with_shares(db.conn, _draft(10000, 2, 5000, 5000), 222)
        bal2 = await repository.get_open_balance(db.conn, 1, 2)
        assert bal2.net_cents == -5000  # Mark now owes Alex 50
    finally:
        await db.close()


async def test_insert_rejects_unbalanced_shares():
    db = await _fresh_db()
    try:
        with pytest.raises(ValueError):
            await repository.insert_expense_with_shares(db.conn, _draft(70000, 1, 40000, 20000), 111)
    finally:
        await db.close()


async def test_open_summary():
    db = await _fresh_db()
    try:
        await repository.insert_expense_with_shares(db.conn, _draft(70000, 1, 50000, 20000), 111)
        await repository.insert_expense_with_shares(db.conn, _draft(30000, 2, 15000, 15000), 222)
        summary = await repository.get_open_summary(db.conn, 1, 2)

        assert len(summary.items) == 2
        assert summary.paid == {1: 70000, 2: 30000}   # totals paid per partner
        assert summary.owed == {1: 65000, 2: 35000}   # totals of own shares
        assert summary.balance.net_cents == 5000       # Mark is owed 50
        assert summary.balance.creditor_id == 1
    finally:
        await db.close()


async def test_recent_returns_open_only():
    db = await _fresh_db()
    try:
        await repository.insert_expense_with_shares(db.conn, _draft(70000, 1, 50000, 20000), 111)
        await repository.settle(db.conn, 1, 2)
        await repository.insert_expense_with_shares(db.conn, _draft(10000, 2, 5000, 5000), 222)
        recent = await repository.get_recent(db.conn, limit=10, open_only=True)
        assert len(recent) == 1
        assert recent[0].total_cents == 10000
        assert recent[0].shares == {1: 5000, 2: 5000}
    finally:
        await db.close()
