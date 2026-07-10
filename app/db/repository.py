"""Data-access functions over the ledger. All money is integer cents.

These operate on an ``aiosqlite.Connection`` so they are trivially testable
against an in-memory database.
"""
from __future__ import annotations

from datetime import datetime

import aiosqlite

from app.models import Balance, ExpenseDraft, OpenSummary, RecentExpense


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def insert_expense_with_shares(
    conn: aiosqlite.Connection,
    draft: ExpenseDraft,
    created_by_tg: int | None,
) -> int:
    """Insert an expense and its per-partner shares atomically. Returns the id.

    Enforces the ledger invariant that the shares re-sum to the total.
    """
    if not draft.is_balanced():
        raise ValueError(
            f"shares {draft.shares_sum()} do not sum to total {draft.total_cents}"
        )

    cursor = await conn.execute(
        """
        INSERT INTO expenses
            (description, total_cents, paid_by, expense_date,
             created_at, created_by_tg, settlement_id, raw_input)
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            draft.description,
            draft.total_cents,
            draft.paid_by,
            draft.expense_date,
            _now(),
            created_by_tg,
            draft.raw_input,
        ),
    )
    expense_id = cursor.lastrowid
    assert expense_id is not None

    await conn.executemany(
        """
        INSERT INTO expense_shares (expense_id, partner_id, share_cents)
        VALUES (?, ?, ?)
        """,
        [(expense_id, pid, cents) for pid, cents in draft.shares.items()],
    )
    await conn.commit()
    return expense_id


async def _paid_total(conn: aiosqlite.Connection, partner_id: int) -> int:
    row = await conn.execute_fetchall(
        """
        SELECT COALESCE(SUM(total_cents), 0) AS s
        FROM expenses
        WHERE settlement_id IS NULL AND paid_by = ?
        """,
        (partner_id,),
    )
    return int(row[0]["s"])


async def _share_total(conn: aiosqlite.Connection, partner_id: int) -> int:
    row = await conn.execute_fetchall(
        """
        SELECT COALESCE(SUM(s.share_cents), 0) AS s
        FROM expense_shares s
        JOIN expenses e ON e.id = s.expense_id
        WHERE e.settlement_id IS NULL AND s.partner_id = ?
        """,
        (partner_id,),
    )
    return int(row[0]["s"])


async def get_open_balance(
    conn: aiosqlite.Connection, partner1_id: int, partner2_id: int
) -> Balance:
    """Net position over OPEN expenses, signed from partner 1's perspective."""
    net_p1 = await _paid_total(conn, partner1_id) - await _share_total(conn, partner1_id)
    return Balance(partner1_id=partner1_id, partner2_id=partner2_id, net_cents=net_p1)


async def count_open(conn: aiosqlite.Connection) -> int:
    row = await conn.execute_fetchall(
        "SELECT COUNT(*) AS c FROM expenses WHERE settlement_id IS NULL"
    )
    return int(row[0]["c"])


async def settle(
    conn: aiosqlite.Connection,
    partner1_id: int,
    partner2_id: int,
    note: str | None = None,
) -> tuple[Balance, int]:
    """Snapshot the current open balance and close every open expense.

    Returns the balance that was settled and the new settlement id. All open
    expenses are stamped with that id, so future balances start from zero.
    """
    balance = await get_open_balance(conn, partner1_id, partner2_id)

    if balance.net_cents > 0:
        direction = "p2_owes_p1"
    elif balance.net_cents < 0:
        direction = "p1_owes_p2"
    else:
        direction = "even"

    cursor = await conn.execute(
        """
        INSERT INTO settlements (settled_at, net_cents, direction, note)
        VALUES (?, ?, ?, ?)
        """,
        (_now(), balance.magnitude_cents, direction, note),
    )
    settlement_id = cursor.lastrowid
    assert settlement_id is not None

    await conn.execute(
        "UPDATE expenses SET settlement_id = ? WHERE settlement_id IS NULL",
        (settlement_id,),
    )
    await conn.commit()
    return balance, settlement_id


async def get_open_summary(
    conn: aiosqlite.Connection, partner1_id: int, partner2_id: int
) -> OpenSummary:
    """The full open-ledger overview: every open transaction, how much each
    partner has paid and owes, and the net balance."""
    items = await get_recent(conn, limit=1000, open_only=True)
    paid = {
        partner1_id: await _paid_total(conn, partner1_id),
        partner2_id: await _paid_total(conn, partner2_id),
    }
    owed = {
        partner1_id: await _share_total(conn, partner1_id),
        partner2_id: await _share_total(conn, partner2_id),
    }
    balance = await get_open_balance(conn, partner1_id, partner2_id)
    return OpenSummary(items=items, paid=paid, owed=owed, balance=balance)


async def get_recent(
    conn: aiosqlite.Connection, limit: int = 10, open_only: bool = True
) -> list[RecentExpense]:
    """Most recent expenses (open ones by default), newest first."""
    where = "WHERE settlement_id IS NULL" if open_only else ""
    rows = await conn.execute_fetchall(
        f"""
        SELECT id, description, total_cents, paid_by, expense_date
        FROM expenses
        {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    if not rows:
        return []

    ids = [int(r["id"]) for r in rows]
    placeholders = ",".join("?" for _ in ids)
    share_rows = await conn.execute_fetchall(
        f"""
        SELECT expense_id, partner_id, share_cents
        FROM expense_shares
        WHERE expense_id IN ({placeholders})
        """,
        ids,
    )
    shares_by_expense: dict[int, dict[int, int]] = {}
    for sr in share_rows:
        shares_by_expense.setdefault(int(sr["expense_id"]), {})[
            int(sr["partner_id"])
        ] = int(sr["share_cents"])

    return [
        RecentExpense(
            id=int(r["id"]),
            description=r["description"],
            total_cents=int(r["total_cents"]),
            paid_by=int(r["paid_by"]),
            expense_date=r["expense_date"],
            shares=shares_by_expense.get(int(r["id"]), {}),
        )
        for r in rows
    ]
