"""
payments.py — Telegram Stars monetisation for MEDIAFLOW BOT
Docs: https://core.telegram.org/bots/payments-stars
"""

import logging
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
)
from telegram.ext import ContextTypes

from database import activate_premium, get_user

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

STARS_PRICE = 100           # Telegram Stars per month
PAYLOAD_PREFIX = "premium_monthly_"


# ─────────────────────────────────────────────
# Send invoice
# ─────────────────────────────────────────────

async def send_upgrade_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a Telegram Stars payment invoice to the user."""
    user = update.effective_user
    payload = f"{PAYLOAD_PREFIX}{user.id}"

    await context.bot.send_invoice(
        chat_id=user.id,
        title="💎 MEDIAFLOW Premium — 1 Month",
        description=(
            "✅ Unlimited video downloads\n"
            "✅ TikTok, Instagram, Facebook, YouTube\n"
            "✅ Priority processing\n"
            "✅ No daily limits — ever"
        ),
        payload=payload,
        currency="XTR",                   # XTR = Telegram Stars
        prices=[LabeledPrice("1 Month Premium", STARS_PRICE)],
        # Stars payments need no provider_token (pass empty string)
        provider_token="",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"⭐ Pay {STARS_PRICE} Stars",
                pay=True,
            )],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")],
        ]),
    )


# ─────────────────────────────────────────────
# Pre-checkout handler (must answer within 10 s)
# ─────────────────────────────────────────────

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    # Validate payload
    if query.invoice_payload.startswith(PAYLOAD_PREFIX):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Invalid payment payload.")


# ─────────────────────────────────────────────
# Successful payment handler
# ─────────────────────────────────────────────

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment = update.message.successful_payment
    user_id = update.effective_user.id

    activate_premium(
        telegram_id=user_id,
        stars_amount=payment.total_amount,
        payload=payment.invoice_payload,
    )

    db_user = get_user(user_id)
    expiry = db_user["subscription_end"] if db_user else "next month"

    await update.message.reply_text(
        f"🎉 *Payment successful!*\n\n"
        f"Welcome to *MEDIAFLOW Premium*! ⭐\n"
        f"Your subscription is active until: `{expiry}`\n\n"
        f"Enjoy *unlimited* downloads — send me any video link!",
        parse_mode="Markdown",
    )
    logger.info("Premium activated for user %s (paid %s Stars)", user_id, payment.total_amount)
