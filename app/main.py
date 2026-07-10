"""Application entrypoint: build the bot, wire handlers, manage the DB
lifecycle, and start long polling."""
from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.bot import handlers
from app.bot.conversation import build_conversation_handler
from app.config import get_settings
from app.db.database import Database

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
# python-telegram-bot is chatty at DEBUG/INFO on the network layer.
logging.getLogger("httpx").setLevel(logging.WARNING)

log = logging.getLogger("fairshare")

_COMMANDS = [
    BotCommand("add", "Log an expense: /add Lunch 450, my share 250"),
    BotCommand("summary", "Open transactions, totals, and who owes whom"),
    BotCommand("balance", "Who owes whom right now"),
    BotCommand("recent", "Recent open expenses"),
    BotCommand("settle", "Settle up and reset the balance"),
    BotCommand("cancel", "Abandon the current draft"),
    BotCommand("help", "How to use FairShare"),
]


async def _post_init(app: Application) -> None:
    settings = get_settings()
    db = Database(settings)
    await db.connect()
    app.bot_data["db"] = db
    await app.bot.set_my_commands(_COMMANDS)
    log.info("Database ready at %s; bot initialized.", settings.db_path)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("handler error while processing update: %s", context.error)


async def _post_shutdown(app: Application) -> None:
    db = app.bot_data.get("db")
    if db is not None:
        await db.close()
        log.info("Database connection closed.")


def main() -> None:
    settings = get_settings()
    allowed = filters.User(user_id=list(settings.allowed_telegram_ids))

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    # Group 0: the expense-entry state machine + whitelisted commands.
    app.add_handler(build_conversation_handler())
    app.add_handler(CommandHandler("start", handlers.start_cmd, filters=allowed))
    app.add_handler(CommandHandler("help", handlers.help_cmd, filters=allowed))
    app.add_handler(CommandHandler("summary", handlers.summary_cmd, filters=allowed))
    app.add_handler(CommandHandler("balance", handlers.balance_cmd, filters=allowed))
    app.add_handler(CommandHandler("recent", handlers.recent_cmd, filters=allowed))
    app.add_handler(CommandHandler("settle", handlers.settle_cmd, filters=allowed))
    app.add_handler(CallbackQueryHandler(handlers.settle_callback, pattern="^st:"))

    app.add_error_handler(_on_error)

    # Group 1: refuse non-whitelisted users, but only in private chats — the bot
    # must stay silent to strangers/other members in group chats.
    app.add_handler(
        MessageHandler(~allowed & filters.ChatType.PRIVATE, handlers.deny), group=1
    )

    log.info("Starting FairShare bot (long polling)…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
