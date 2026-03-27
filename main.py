"""
main.py — MEDIAFLOW BOT entry point
Run: python main.py
"""

import logging
import os

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from database import init_db
from downloader import cleanup_old_temps
from handlers import callback_handler, help_handler, message_handler, start_handler
from payments import precheckout_handler, successful_payment_handler

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("yt_dlp").setLevel(logging.WARNING)

logger = logging.getLogger(name)


# ─────────────────────────────────────────────
# Periodic jobs
# ─────────────────────────────────────────────

async def cleanup_job(context) -> None:
    cleanup_old_temps(max_age_seconds=3600)


# ─────────────────────────────────────────────
# Post-init (register bot commands menu)
# ─────────────────────────────────────────────

async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Show welcome screen & menu"),
        BotCommand("help",  "How to use MEDIAFLOW BOT"),
    ])
    logger.info("Bot commands registered ✓")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set.\n"
            "Get your token from @BotFather and run:  export BOT_TOKEN=<token>"
        )

    init_db()

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .concurrent_updates(True)
        .build()
    )

    # Commands — pass_args=True so /start <referral_id> works
    app.add_handler(CommandHandler("start", start_handler, has_args=None))
    app.add_handler(CommandHandler("help",  help_handler))

    # Payments
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    # All text messages (including URLs and button taps)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Hourly temp-file cleanup
    app.job_queue.run_repeating(cleanup_job, interval=3600, first=3600)

    logger.info("🚀 MEDIAFLOW BOT is starting…")
    app.run_polling(drop_pending_updates=True)


if name == "main":
    main()
