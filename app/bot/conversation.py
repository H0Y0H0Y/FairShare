"""The expense-entry state machine.

A single ``ConversationHandler`` locks each entry into an isolated lifecycle:

    input (text / photo / photo+caption)
        -> parse -> draft in context.user_data -> CONFIRMING
    CONFIRMING: [Confirm] -> write to DB -> clear -> END
                [Edit]    -> ADJUSTING
                [Cancel]  -> clear -> END
    ADJUSTING:  free-text correction -> re-parse -> CONFIRMING

The draft lives only in ``context.user_data`` until confirmed, so the database
is never touched mid-flow and concurrent messages cannot corrupt an entry.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import date

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.ai.parser import ParseError, merge_expense, parse_expense
from app.bot.keyboards import CB_CANCEL, CB_CONFIRM, CB_EDIT, draft_keyboard
from app.bot.views import render_balance, render_draft
from app.config import get_settings
from app.db import repository

log = logging.getLogger(__name__)

# Conversation states
CONFIRMING, ADJUSTING = range(2)

_DRAFT_KEY = "draft"

# Strips a leading "/add" (optionally "/add@BotName") so group entries logged as
# "/add Lunch 450, my share 250" parse the same as a private-chat message.
_ADD_PREFIX = re.compile(r"^/add(@\w+)?\s*", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Entry: parse a fresh message into a draft
# --------------------------------------------------------------------------- #
async def on_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings = get_settings()
    message = update.effective_message
    user = update.effective_user
    sender = settings.partner_by_telegram_id(user.id)
    if sender is None:  # should be filtered upstream, but guard anyway
        return ConversationHandler.END

    image_b64: str | None = None
    media_type = "image/jpeg"
    if message.photo:
        photo_file = await message.photo[-1].get_file()
        raw = await photo_file.download_as_bytearray()
        image_b64 = base64.b64encode(bytes(raw)).decode("ascii")
        text = message.caption
    else:
        text = message.text

    # In groups the entry is "/add <expense>"; drop that prefix before parsing.
    if text:
        text = _ADD_PREFIX.sub("", text).strip() or None

    if not text and image_b64 is None:
        await message.reply_text(
            "Add an expense after the command, e.g. “/add Lunch 450, my share 250”, "
            "or send a receipt photo."
        )
        return ConversationHandler.END

    await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
    try:
        draft = await parse_expense(
            text=text,
            image_b64=image_b64,
            image_media_type=media_type,
            sender=sender,
            today=date.today().isoformat(),
        )
    except ParseError as exc:
        log.warning("parse failed: %s", exc)
        await message.reply_text(
            "I couldn't read that as an expense. Try again with an amount, "
            "e.g. “Dinner 700, my share 500, yours 200”."
        )
        return ConversationHandler.END
    except Exception:  # network/model failure
        log.exception("unexpected parse error")
        await message.reply_text("⚠️ Something went wrong reaching the AI. Please try again.")
        return ConversationHandler.END

    context.user_data[_DRAFT_KEY] = draft
    await message.reply_text(
        render_draft(draft, settings),
        parse_mode=ParseMode.HTML,
        reply_markup=draft_keyboard(),
    )
    return CONFIRMING


# --------------------------------------------------------------------------- #
# CONFIRMING: handle the inline-button choice
# --------------------------------------------------------------------------- #
async def on_confirm_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings = get_settings()
    query = update.callback_query
    await query.answer()
    draft = context.user_data.get(_DRAFT_KEY)
    log.info(
        "callback %s in %s chat from user %s; draft=%s",
        query.data, update.effective_chat.type, update.effective_user.id, draft is not None,
    )

    if draft is None:  # draft lost (timeout/restart)
        await query.edit_message_text("This draft has expired. Send the expense again.")
        return ConversationHandler.END

    if query.data == CB_CANCEL:
        context.user_data.clear()
        await query.edit_message_text("❌ Cancelled. Nothing was saved.")
        return ConversationHandler.END

    if query.data == CB_EDIT:
        in_group = update.effective_chat.type != "private"
        reply_hint = " (in a group, <b>reply</b> to this message)" if in_group else ""
        await query.edit_message_text(
            render_draft(draft, settings)
            + f"\n\n✏️ Send a correction{reply_hint} — e.g. “my share 400”, "
            "“paid by them”, “date yesterday”, “total 720” — "
            "or send the receipt photo to re-read it.",
            parse_mode=ParseMode.HTML,
        )
        return ADJUSTING

    if query.data == CB_CONFIRM:
        if not draft.is_balanced():
            await query.answer("Shares don't sum to the total — edit first.", show_alert=True)
            return CONFIRMING
        db = context.bot_data["db"]
        user = update.effective_user
        await repository.insert_expense_with_shares(db.conn, draft, user.id)
        p1, p2 = settings.partners[0].id, settings.partners[1].id
        balance = await repository.get_open_balance(db.conn, p1, p2)
        context.user_data.clear()
        await query.edit_message_text(
            "✅ <b>Saved.</b>\n" + render_balance(balance, settings),
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    return CONFIRMING


# --------------------------------------------------------------------------- #
# ADJUSTING: apply a natural-language correction
# --------------------------------------------------------------------------- #
async def on_adjust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings = get_settings()
    message = update.effective_message
    user = update.effective_user
    sender = settings.partner_by_telegram_id(user.id)
    draft = context.user_data.get(_DRAFT_KEY)
    if draft is None or sender is None:
        return ConversationHandler.END

    log.info("adjust correction received in %s chat: %r", update.effective_chat.type, message.text)
    await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
    try:
        updated = await merge_expense(
            current=draft,
            correction=message.text,
            sender=sender,
            today=date.today().isoformat(),
        )
    except ParseError as exc:
        log.warning("merge failed: %s", exc)
        await message.reply_text("I couldn't apply that change. Try rephrasing it.")
        return ADJUSTING
    except Exception:
        log.exception("unexpected merge error")
        await message.reply_text("⚠️ Something went wrong. Try again.")
        return ADJUSTING

    context.user_data[_DRAFT_KEY] = updated
    await message.reply_text(
        render_draft(updated, settings),
        parse_mode=ParseMode.HTML,
        reply_markup=draft_keyboard(),
    )
    return CONFIRMING


# --------------------------------------------------------------------------- #
# Fallbacks
# --------------------------------------------------------------------------- #
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("❌ Cancelled. Nothing was saved.")
    return ConversationHandler.END


async def on_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⏳ Draft expired. Send the expense again when you're ready."
        )
    return ConversationHandler.END


def build_conversation_handler() -> ConversationHandler:
    settings = get_settings()
    allowed = filters.User(user_id=list(settings.allowed_telegram_ids))
    content = allowed & ~filters.COMMAND
    private = filters.ChatType.PRIVATE

    return ConversationHandler(
        entry_points=[
            # Private chat: any text or photo is treated as an expense.
            MessageHandler(content & private & filters.PHOTO, on_input),
            MessageHandler(content & private & filters.TEXT, on_input),
            # Any chat (esp. groups): explicit "/add <expense>" command, and
            # photos whose caption starts with /add. Works under Group Privacy.
            CommandHandler("add", on_input, filters=allowed),
            MessageHandler(
                allowed & filters.PHOTO & filters.CaptionRegex(r"(?i)^/add(@\w+)?\b"),
                on_input,
            ),
        ],
        states={
            CONFIRMING: [CallbackQueryHandler(on_confirm_choice, pattern="^cf:")],
            ADJUSTING: [
                # A receipt photo re-reads the expense from the image (replaces draft).
                MessageHandler(content & filters.PHOTO, on_input),
                # A text message is a natural-language correction.
                MessageHandler(content & filters.TEXT, on_adjust),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, on_timeout),
                CallbackQueryHandler(on_timeout),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel, filters=allowed)],
        conversation_timeout=settings.draft_timeout,
        per_user=True,
        per_chat=True,
        name="expense_flow",
    )
