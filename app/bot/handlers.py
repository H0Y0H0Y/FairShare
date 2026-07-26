"""Standalone commands: /start, /help, /balance, /recent, /settle, plus a
refusal handler for non-whitelisted users.

The expense-entry flow lives in ``conversation.py``; these are the stateless
commands that sit alongside it.
"""
from __future__ import annotations

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.bot.views import mention, render_balance, render_recent, render_summary
from app.config import get_settings
from app.db import repository
from app.utils.money import format_cents

log = logging.getLogger(__name__)

CB_SETTLE_YES = "st:yes"
CB_SETTLE_NO = "st:no"

CB_DEL_PICK = "del:pick:"  # + expense id
CB_DEL_YES = "del:yes:"    # + expense id
CB_DEL_NO = "del:no"

_HELP = (
    "🤝 <b>FairShare</b> — shared expense tracker\n\n"
    "<b>In a private chat with me</b>, just send the expense:\n"
    "• <i>text</i> — “Dinner 700, my share 500, yours 200”\n"
    "• <i>a receipt photo</i> — I'll read the total\n"
    "• <i>photo + caption</i> — I'll combine both\n\n"
    "<b>In a group</b>, prefix it with /add:\n"
    "• “/add Lunch 450, my share 250”\n"
    "• a photo captioned “/add …”\n"
    "• to edit a draft in a group, <i>reply</i> to my message\n\n"
    "I'll show a draft; tap ✅ Confirm, ✏️ Edit, or ❌ Cancel.\n\n"
    "<b>Commands</b>\n"
    "/summary — open transactions, totals, and who owes whom\n"
    "/balance — who owes whom right now\n"
    "/recent — recent open expenses\n"
    "/delete — remove an expense logged by mistake\n"
    "/settle — mark everything settled and reset the balance\n"
    "/cancel — abandon the current draft\n"
    "/help — this message"
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_HELP, parse_mode=ParseMode.HTML)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_HELP, parse_mode=ParseMode.HTML)


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    db = context.bot_data["db"]
    p1, p2 = settings.partners[0].id, settings.partners[1].id
    balance = await repository.get_open_balance(db.conn, p1, p2)
    await update.effective_message.reply_text(
        render_balance(balance, settings), parse_mode=ParseMode.HTML
    )


async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open transactions + per-partner totals + who owes whom."""
    settings = get_settings()
    db = context.bot_data["db"]
    p1, p2 = settings.partners[0].id, settings.partners[1].id
    summary = await repository.get_open_summary(db.conn, p1, p2)
    await update.effective_message.reply_text(
        render_summary(summary, settings), parse_mode=ParseMode.HTML
    )


async def recent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    db = context.bot_data["db"]
    items = await repository.get_recent(db.conn, limit=10, open_only=True)
    await update.effective_message.reply_text(
        render_recent(items, settings), parse_mode=ParseMode.HTML
    )


async def settle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the current balance and ask for confirmation before closing."""
    settings = get_settings()
    db = context.bot_data["db"]
    p1, p2 = settings.partners[0].id, settings.partners[1].id
    open_count = await repository.count_open(db.conn)
    if open_count == 0:
        await update.effective_message.reply_text("Nothing to settle — no open expenses.")
        return
    balance = await repository.get_open_balance(db.conn, p1, p2)
    balance_line = render_balance(balance, settings)

    # Only the creditor may confirm, so only show the button to them. In a group
    # the message (and its button) is visible to both partners, so we gate on who
    # ran /settle: the person confirming must be the one who is owed.
    caller = settings.partner_by_telegram_id(update.effective_user.id)
    if caller is None or not balance.may_confirm_settle(caller.id):
        creditor = settings.partner_by_id(balance.creditor_id)
        await update.effective_message.reply_text(
            balance_line
            + f"\n\nOnly {mention(creditor)} — who is owed — can settle. "
            f"Ask them to run /settle to confirm.",
            parse_mode=ParseMode.HTML,
        )
        return

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Settle & reset", callback_data=CB_SETTLE_YES),
                InlineKeyboardButton("❌ Keep open", callback_data=CB_SETTLE_NO),
            ]
        ]
    )
    await update.effective_message.reply_text(
        balance_line
        + f"\n\nSettling will close {open_count} open expense(s) and reset the balance to zero."
        + "\n\nProceed?",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def settle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    query = update.callback_query
    # A settle-confirmation message is visible to everyone in a group, so a
    # non-partner could tap the button. Authorize the tapper before acting.
    if query.from_user.id not in settings.allowed_telegram_ids:
        await query.answer("You're not authorized to use this bot.", show_alert=True)
        return
    if query.data == CB_SETTLE_NO:
        await query.answer()
        await query.edit_message_text("Kept open. Nothing changed.")
        return

    db = context.bot_data["db"]
    p1, p2 = settings.partners[0].id, settings.partners[1].id

    # Only the partner who is owed may confirm the settlement — they're the one
    # acknowledging the money reached them. Whoever opened /settle, the button is
    # visible to both, so gate the destructive action on the creditor here.
    balance = await repository.get_open_balance(db.conn, p1, p2)
    tapper = settings.partner_by_telegram_id(query.from_user.id)
    if tapper is None or not balance.may_confirm_settle(tapper.id):
        creditor = settings.partner_by_id(balance.creditor_id)
        await query.answer(
            f"Only {creditor.name} — who is owed — can confirm this is settled.",
            show_alert=True,
        )
        return

    await query.answer()
    balance, _settlement_id = await repository.settle(db.conn, p1, p2)
    settled_line = render_balance(balance, settings)
    await query.edit_message_text(
        "🧾 <b>Settled.</b>\n"
        + settled_line
        + "\nBalance reset to zero. New expenses start a fresh tally.",
        parse_mode=ParseMode.HTML,
    )


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List open expenses as buttons so one can be picked for deletion."""
    settings = get_settings()
    db = context.bot_data["db"]
    items = await repository.get_recent(db.conn, limit=10, open_only=True)
    if not items:
        await update.effective_message.reply_text("Nothing to delete — no open expenses.")
        return
    rows = []
    for e in items:
        label = f"{e.description} · {format_cents(e.total_cents, settings.currency_symbol)} · {e.expense_date[5:]}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"{CB_DEL_PICK}{e.id}")])
    rows.append([InlineKeyboardButton("✖️ Close", callback_data=CB_DEL_NO)])
    await update.effective_message.reply_text(
        "🗑 <b>Delete which expense?</b>\n<i>Only open expenses are listed. Deletion is permanent.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    query = update.callback_query
    # Buttons are visible to everyone in a group — authorize the tapper.
    if query.from_user.id not in settings.allowed_telegram_ids:
        await query.answer("You're not authorized to use this bot.", show_alert=True)
        return
    await query.answer()
    db = context.bot_data["db"]
    data = query.data

    if data == CB_DEL_NO:
        await query.edit_message_text("Closed. Nothing was deleted.")
        return

    if data.startswith(CB_DEL_PICK):
        expense_id = int(data[len(CB_DEL_PICK):])
        e = await repository.get_expense(db.conn, expense_id, open_only=True)
        if e is None:
            await query.edit_message_text("That expense is no longer available.")
            return
        payer = settings.partner_by_id(e.paid_by)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🗑 Delete", callback_data=f"{CB_DEL_YES}{expense_id}"),
                    InlineKeyboardButton("↩️ Cancel", callback_data=CB_DEL_NO),
                ]
            ]
        )
        await query.edit_message_text(
            f"Delete <b>{escape(e.description)}</b> · "
            f"{format_cents(e.total_cents, settings.currency_symbol)} "
            f"({e.expense_date}, paid by {escape(payer.name)})?\n"
            f"<i>This can't be undone.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return

    if data.startswith(CB_DEL_YES):
        expense_id = int(data[len(CB_DEL_YES):])
        ok = await repository.delete_expense(db.conn, expense_id)
        if not ok:
            await query.edit_message_text("That expense was already removed or is settled.")
            return
        p1, p2 = settings.partners[0].id, settings.partners[1].id
        balance = await repository.get_open_balance(db.conn, p1, p2)
        await query.edit_message_text(
            "🗑 <b>Deleted.</b>\n" + render_balance(balance, settings),
            parse_mode=ParseMode.HTML,
        )
        return


async def deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Politely refuse anyone not on the whitelist."""
    if update.effective_message:
        await update.effective_message.reply_text(
            "Sorry, this is a private bot and you're not authorized to use it."
        )
    log.info("denied user id=%s", update.effective_user.id if update.effective_user else "?")
