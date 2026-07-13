"""File Store Telegram Bot — main entry point.

Run with:  python -m bot  OR  python main.py
Bot uses long polling. No webhook/domain/SSL needed.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import cfg
from db import init_db, seed_defaults, get_session
from handlers.start import (
    cmd_start,
    cmd_admin,
    text_menu,
)
from handlers.callbacks import callback_router
from handlers.shop import handle_state
from handlers.admin import handle_admin_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("seller")


def startup() -> None:
    """Initialise database and seed defaults."""
    init_db()
    s = get_session()
    try:
        seed_defaults(s)
    finally:
        s.close()
    log.info("Database initialised at %s", cfg.database_url)
    if not cfg.bot_token or cfg.bot_token.startswith("123456:"):
        log.warning("BOT_TOKEN looks invalid — make sure you set it in .env")


async def post_init(app: Application) -> None:
    startup()
    me = await app.bot.get_me()
    log.info("Bot @%s connected (%d admins registered)", me.username, len(cfg.admin_ids))


def build_app() -> Application:
    kwargs = cfg.get_proxy_request_kwargs()
    app = (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .post_init(post_init)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(60)
        .pool_timeout(60)
    )
    if cfg.telegram_api_base:
        import httpx

        app = app.base_url(cfg.telegram_api_base).base_file_url(cfg.telegram_api_base)
    app = app.build()
    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("cancel", cmd_admin))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, text_menu))
    return app


def main() -> None:
    startup()
    log.info("Starting long-polling bot…")
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
