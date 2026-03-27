"""
handlers.py — All bot handlers for MEDIAFLOW BOT
"""

import logging
import time
from collections import defaultdict

from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import database as db
from database import FREE_DAILY_LIMIT
from downloader import cleanup_file, detect_platform, download_video, is_valid_url
from payments import send_upgrade_invoice

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Rate limiting (in-memory, resets on restart)
# ─────────────────────────────────────────────

_rate_map: dict[int, list[float]] = defaultdict(list)
RATE_WINDOW = 60        # seconds
RATE_MAX_CALLS = 10     # max requests per window per user


def _is_rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    calls = _rate_map[user_id]
    # remove old entries
    _rate_map[user_id] = [t for t in calls if now - t < RATE_WINDOW]
    if len(_rate_map[user_id]) >= RATE_MAX_CALLS:
        return True
    _rate_map[user_id].append(now)
    return False


# ─────────────────────────────────────────────
# Keyboard layout
# ─────────────────────────────────────────────

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📥 Download Video"), KeyboardButton("📊 My Plan")],
        [KeyboardButton("💎 Upgrade"),         KeyboardButton("ℹ️ Help")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Paste a video link or choose an option…",
)

# ─────────────────────────────────────────────
# Text helpers
# ─────────────────────────────────────────────

SUPPORTED_PLATFORMS = "TikTok · Instagram · Facebook · YouTube"

WELCOME_TEXT = (
    "👋 Welcome to *MEDIAFLOW BOT*!\n\n"
    "Download videos from:\n"
    f"🎵 TikTok (no watermark)\n"
    f"📸 Instagram\n"
    f"📘 Facebook\n"
    f"▶️ YouTube\n\n"
    f"*Free plan:* {FREE_DAILY_LIMIT} downloads/day\n"
    f"*Premium:* Unlimited downloads ⭐\n\n"
    f"Just send me a video link to get started!"
)

HELP_TEXT = (
    "ℹ️ *MEDIAFLOW BOT — Help*\n\n"
    "*How to download:*\n"
    "1. Copy a video link from TikTok, Instagram, Facebook, or YouTube\n"
    "2. Paste it here and send\n"
    "3. Receive your video in seconds!\n\n"
    "*Limits:*\n"
    f"• Free users: {FREE_DAILY_LIMIT} downloads per day\n"
    "• Premium users: unlimited\n\n"
    "*Upgrade:*\n"
    "Tap 💎 Upgrade and pay 100 Telegram Stars for 1 month of unlimited access.\n\n"
    "*Supported:*\n"
    f"`{SUPPORTED_PLATFORMS}`\n\n"
    "*Issues?* Make sure the link is public and try again."
)
ADMIN_ID = 8309843074   # your Telegram user ID

async def stats_handler(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    stats = db.get_stats()
    await update.message.reply_text(
        f"📊 Stats\n"
        f"Total users: {stats['total_users']}\n"
        f"Premium users: {stats['premium_users']}\n"
        f"Downloads today: {stats['downloads_today']}"
    )

def _plan_text(user: dict) -> str:
    if user["is_premium"]:
        expiry = user.get("subscription_end") or "∞"
        return (
            "📊 *Your Plan: Premium* ⭐\n\n"
            f"• Unlimited downloads\n"
            f"• Subscription expires: `{expiry}`\n\n"
            "Thank you for supporting MEDIAFLOW BOT! 🙏"
        )
    remaining = max(0, FREE_DAILY_LIMIT - user["downloads_used"])
    return (
        "📊 *Your Plan: Free*\n\n"
        f"• Downloads today: {user['downloads_used']} / {FREE_DAILY_LIMIT}\n"
        f"• Remaining today: {remaining}\n"
        f"• Resets: daily at midnight UTC\n\n"
        "Upgrade to Premium for *unlimited* downloads! 👇\n"
        "Tap 💎 Upgrade below."
    )


# ─────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.first_name)
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


# ─────────────────────────────────────────────
# Button / text message router
# ─────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = (update.message.text or "").strip()

    # Ensure user exists
    db.upsert_user(user.id, user.username, user.first_name)

    # ── Keyboard button actions ──────────────────
    if text == "📥 Download Video":
        await update.message.reply_text(
            "📎 Send me a video link from TikTok, Instagram, Facebook, or YouTube.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if text == "📊 My Plan":
        db_user = db.get_user(user.id)
        await update.message.reply_text(
            _plan_text(db_user),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if text == "💎 Upgrade":
        await send_upgrade_invoice(update, context)
        return

    if text == "ℹ️ Help":
        await update.message.reply_text(
            HELP_TEXT,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # ── URL detection ────────────────────────────
    if not text.startswith(("http://", "https://")):
        await update.message.reply_text(
            "🤔 I didn't understand that. Please send a video link or use the menu.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # ── Rate limit guard ─────────────────────────
    if _is_rate_limited(user.id):
        await update.message.reply_text(
            "⏳ You're sending requests too fast. Please wait a moment.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # ── Validate URL ─────────────────────────────
    if not is_valid_url(text):
        platform = detect_platform(text)
        if platform is None:
            await update.message.reply_text(
                f"❌ Unsupported link.\n\nSupported platforms:\n`{SUPPORTED_PLATFORMS}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=MAIN_KEYBOARD,
            )
        else:
            await update.message.reply_text(
                "❌ That doesn't look like a valid video link. Please check and try again.",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    # ── Quota check ──────────────────────────────
    allowed, db_user = db.can_download(user.id)
    if not allowed:
        await update.message.reply_text(
            f"🚫 You've used all *{FREE_DAILY_LIMIT}* free downloads for today.\n\n"
            "Upgrade to *Premium* for unlimited downloads!\n"
            "Tap 💎 Upgrade below.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD,
        )
        await send_upgrade_invoice(update, context)
        return

    # ── Download flow ─────────────────────────────
    platform = detect_platform(text)
    status_msg = await update.message.reply_text(
        f"⏳ Downloading from *{platform.title()}*…",
        parse_mode=ParseMode.MARKDOWN,
    )

    result = await download_video(text)

    if not result.success:
        await status_msg.edit_text(
            f"❌ *Download failed*\n\n{result.error}\n\n"
            "Please make sure the video is public and try again.",
            parse_mode=ParseMode.MARKDOWN,
        )
        db.log_download(user.id, platform or "unknown", text, success=False)
        return

    # Upload
    await status_msg.edit_text("📤 Uploading video…")
    try:
        with open(result.file_path, "rb") as video_file:
            caption = (
                f"✅ *{result.title or 'Video'}*\n"
                f"Platform: {platform.title()}\n"
                f"Via @MediaFlowBot"
            )
            await update.message.reply_video(
                video=video_file,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                supports_streaming=True,
            )
        await status_msg.delete()

        # Increment counter only after successful delivery
        db.increment_downloads(user.id)
        db.log_download(user.id, platform, text, success=True)

        # Show remaining quota to free users
        if not db_user["is_premium"]:
            used = db_user["downloads_used"] + 1
            remaining = max(0, FREE_DAILY_LIMIT - used)
            if remaining == 0:
                await update.message.reply_text(
                    "⚠️ That was your last free download for today.\n"
                    "Upgrade to Premium for unlimited access! 💎",
                    reply_markup=MAIN_KEYBOARD,
                )
            else:
                await update.message.reply_text(
                    f"✅ Done! You have *{remaining}* free download(s) left today.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=MAIN_KEYBOARD,
                )

    except Exception as exc:
        logger.exception("Upload error: %s", exc)
        await status_msg.edit_text(
            "❌ Failed to send the video. The file may be too large for Telegram.",
        )
    finally:
        if result.file_path:
            cleanup_file(result.file_path)


# ─────────────────────────────────────────────
# Callback query handler (cancel payment button)
# ─────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_payment":
        await query.message.delete()
