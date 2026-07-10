"""Message-rendering helpers shared by the conversation flow and commands.

Kept separate from handlers to avoid an import cycle (conversation <-> handlers).
Output uses Telegram HTML parse mode.
"""
from __future__ import annotations

from html import escape

from app.config import Settings
from app.models import Balance, ExpenseDraft, OpenSummary, RecentExpense
from app.utils.money import format_cents


def _money(cents: int, settings: Settings) -> str:
    return format_cents(cents, settings.currency_symbol)


def render_draft(draft: ExpenseDraft, settings: Settings) -> str:
    payer = settings.partner_by_id(draft.paid_by)
    lines = [
        "🧾 <b>Draft expense</b>",
        f"<b>What:</b> {escape(draft.description)}",
        f"<b>Total:</b> {_money(draft.total_cents, settings)}",
        f"<b>Paid by:</b> {escape(payer.name)}",
        f"<b>Date:</b> {draft.expense_date}",
        "<b>Split:</b>",
    ]
    for p in settings.partners:
        share = draft.shares.get(p.id, 0)
        lines.append(f"  • {escape(p.name)}: {_money(share, settings)}")

    if draft.split_inferred:
        lines.append("\n<i>⚠️ Split was auto-set to 50/50 — edit if that's wrong.</i>")
    if not draft.is_balanced():
        lines.append(
            f"\n<b>⚠️ Shares don't sum to the total</b> "
            f"({_money(draft.shares_sum(), settings)} ≠ {_money(draft.total_cents, settings)}). "
            f"Tap ✏️ Edit to fix before confirming."
        )
    lines.append("\nConfirm to save, or edit the details.")
    return "\n".join(lines)


def render_balance(balance: Balance, settings: Settings) -> str:
    if balance.creditor_id is None:
        return "⚖️ You're all square — no open balance."
    creditor = settings.partner_by_id(balance.creditor_id)
    debtor = settings.partner_by_id(balance.debtor_id)
    amount = _money(balance.magnitude_cents, settings)
    return f"⚖️ <b>{escape(debtor.name)}</b> owes <b>{escape(creditor.name)}</b> {amount}"


def render_summary(summary: OpenSummary, settings: Settings) -> str:
    p1, p2 = settings.partners[0], settings.partners[1]

    if not summary.items:
        return "📊 <b>Open summary</b>\n\nNo open transactions — you're all square. ⚖️"

    lines = [f"📊 <b>Open summary</b> — {len(summary.items)} transaction(s)", ""]
    for e in summary.items:
        payer = settings.partner_by_id(e.paid_by)
        split = " / ".join(
            f"{escape(p.name)} {_money(e.shares.get(p.id, 0), settings)}"
            for p in settings.partners
        )
        lines.append(
            f"#{e.id} · {e.expense_date} · {escape(e.description)} — "
            f"{_money(e.total_cents, settings)}\n"
            f"    paid by {escape(payer.name)} · split: {split}"
        )

    lines.append("")
    lines.append("<b>Totals (open)</b>")
    for p in settings.partners:
        lines.append(
            f"  • {escape(p.name)}: paid {_money(summary.paid.get(p.id, 0), settings)}, "
            f"owes-share {_money(summary.owed.get(p.id, 0), settings)}"
        )

    lines.append("")
    lines.append(render_balance(summary.balance, settings))
    return "\n".join(lines)


def render_recent(items: list[RecentExpense], settings: Settings) -> str:
    if not items:
        return "No open expenses yet."
    lines = ["🗒️ <b>Recent open expenses</b>"]
    for e in items:
        payer = settings.partner_by_id(e.paid_by)
        lines.append(
            f"#{e.id} · {e.expense_date} · {escape(e.description)} — "
            f"{_money(e.total_cents, settings)} (paid by {escape(payer.name)})"
        )
    return "\n".join(lines)
