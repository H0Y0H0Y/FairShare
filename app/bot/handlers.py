"""Standalone commands: /start, /help, /balance, /recent, /settle, plus a
refusal handler for non-whitelisted users.

The expense-entry flow lives in ``conversation.py``; these are the stateless
commands that sit alongside it.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.bot.views import render_balance, render_recent, render_summary
from app.config import get_settings
from app.db import repository

log = logging.getLogger(__name__)

CB_SETTLE_YES = "st:yes"
CB_SETTLE_NO = "st:no"

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
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Settle & reset", callback_data=CB_SETTLE_YES),
                InlineKeyboardButton("❌ Keep open", callback_data=CB_SETTLE_NO),
            ]
        ]
    )
    await update.effective_message.reply_text(
        render_balance(balance, settings)
        + f"\n\nSettling will close {open_count} open expense(s) and reset the balance to zero. Proceed?",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def settle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    query = update.callback_query
    await query.answer()
    if query.data == CB_SETTLE_NO:
        await query.edit_message_text("Kept open. Nothing changed.")
        return

    db = context.bot_data["db"]
    p1, p2 = settings.partners[0].id, settings.partners[1].id
    balance, _settlement_id = await repository.settle(db.conn, p1, p2)
    settled_line = render_balance(balance, settings)
    await query.edit_message_text(
        "🧾 <b>Settled.</b>\n"
        + settled_line
        + "\nBalance reset to zero. New expenses start a fresh tally.",
        parse_mode=ParseMode.HTML,
    )


async def deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Politely refuse anyone not on the whitelist."""
    if update.effective_message:
        await update.effective_message.reply_text(
            "Sorry, this is a private bot and you're not authorized to use it."
        )
    log.info("denied user id=%s", update.effective_user.id if update.effective_user else "?")
