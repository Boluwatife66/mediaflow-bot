"""
downloader.py — yt-dlp wrapper for MEDIAFLOW BOT
Supports: TikTok (no watermark), Instagram, Facebook, YouTube
"""

import asyncio
import logging
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yt_dlp  # type: ignore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Platform detection
# ─────────────────────────────────────────────

PLATFORM_PATTERNS = {
    "tiktok":    re.compile(r"tiktok\.com|vm\.tiktok\.com", re.I),
    "instagram": re.compile(r"instagram\.com|instagr\.am", re.I),
    "facebook":  re.compile(r"facebook\.com|fb\.watch|fb\.com", re.I),
    "youtube":   re.compile(r"youtube\.com|youtu\.be", re.I),
}


def detect_platform(url: str) -> Optional[str]:
    for platform, pattern in PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return platform
    return None


def is_valid_url(url: str) -> bool:
    return url.startswith(("http://", "https://")) and detect_platform(url) is not None


# ─────────────────────────────────────────────
# Download result
# ─────────────────────────────────────────────

@dataclass
class DownloadResult:
    success: bool
    file_path: Optional[str] = None
    title: Optional[str] = None
    platform: Optional[str] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────
# yt-dlp option profiles per platform
# ─────────────────────────────────────────────

TEMP_DIR = Path(tempfile.gettempdir()) / "mediaflow"
TEMP_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE_MB = 50   # Telegram Bot API limit for sendVideo via API


def _build_ydl_opts(platform: str, out_template: str) -> dict:
    """Return yt-dlp options tuned per platform."""
    common = {
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        # keep file size sane — best quality under ~50 MB
        "format": (
            "bestvideo[ext=mp4][filesize<45M]+bestaudio[ext=m4a]"
            "/bestvideo[ext=mp4]+bestaudio"
            "/best[ext=mp4]"
            "/best"
        ),
    }

    if platform == "tiktok":
        common.update({
            # tiktok watermark removal — use the no-watermark CDN feed
            "format": "download_addr-2/download_addr/bestvideo+bestaudio/best",
        })

    if platform == "instagram":
        common.update({
            # Instagram may require cookies; fall back gracefully
            "format": "best[ext=mp4]/best",
        })

    if platform == "youtube":
        common.update({
            # Prefer 720 p to stay under Telegram size limit
            "format": (
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]"
                "/bestvideo[height<=720]+bestaudio"
                "/best[height<=720]"
                "/best"
            ),
        })

    return common


# ─────────────────────────────────────────────
# Core download function (runs in executor)
# ─────────────────────────────────────────────

def _download_sync(url: str, platform: str) -> DownloadResult:
    uid = uuid.uuid4().hex[:10]
    out_template = str(TEMP_DIR / f"{platform}_{uid}.%(ext)s")

    opts = _build_ydl_opts(platform, out_template)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        # Find the file that was written
        candidates = list(TEMP_DIR.glob(f"{platform}_{uid}.*"))
        if not candidates:
            return DownloadResult(success=False, error="No output file found after download.")

        file_path = str(candidates[0])
        size_mb = os.path.getsize(file_path) / 1_048_576

        if size_mb > MAX_FILE_SIZE_MB:
            os.remove(file_path)
            return DownloadResult(
                success=False,
                error=f"Video is too large ({size_mb:.1f} MB). Telegram limit is {MAX_FILE_SIZE_MB} MB.",
            )

        return DownloadResult(success=True, file_path=file_path, title=title, platform=platform)

    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        logger.warning("yt-dlp DownloadError for %s: %s", url, msg)
        # Surface a friendly message
        if "Private" in msg or "Login" in msg or "login" in msg:
            friendly = "This content is private or requires login. Only public videos are supported."
        elif "Unsupported URL" in msg:
            friendly = "URL not supported by the downloader."
        else:
            friendly = "Download failed. The link may be private, expired, or unsupported."
        return DownloadResult(success=False, error=friendly)

    except Exception as exc:
        logger.exception("Unexpected download error: %s", exc)
        return DownloadResult(success=False, error="An unexpected error occurred. Please try again.")


async def download_video(url: str) -> DownloadResult:
    """Async wrapper — runs blocking yt-dlp in a thread pool."""
    platform = detect_platform(url)
    if not platform:
        return DownloadResult(success=False, error="Unsupported platform.")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _download_sync, url, platform)
    return result


# ─────────────────────────────────────────────
# Cleanup helper
# ─────────────────────────────────────────────

def cleanup_file(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
            logger.debug("Removed temp file: %s", path)
    except OSError as exc:
        logger.warning("Could not remove %s: %s", path, exc)


def cleanup_old_temps(max_age_seconds: int = 3600) -> None:
    """Purge temp files older than max_age_seconds (run periodically)."""
    import time
    now = time.time()
    removed = 0
    for f in TEMP_DIR.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > max_age_seconds:
            f.unlink(missing_ok=True)
            removed += 1
    if removed:
        logger.info("Cleaned up %d stale temp files.", removed)
