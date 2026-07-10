"""Inline keyboards and callback-data constants for the confirm/adjust flow."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Callback data tokens (kept short; Telegram limits callback_data to 64 bytes).
CB_CONFIRM = "cf:confirm"
CB_EDIT = "cf:edit"
CB_CANCEL = "cf:cancel"


def draft_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=CB_CONFIRM),
                InlineKeyboardButton("✏️ Edit", callback_data=CB_EDIT),
                InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL),
            ]
        ]
    )
