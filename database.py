"""
database.py — SQLite persistence layer for MEDIAFLOW BOT
"""

import sqlite3
import logging
from datetime import date, datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = "mediaflow.db"

# ─────────────────────────────────────────────
# Connection helper
# ─────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Schema bootstrap
# ─────────────────────────────────────────────

def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id       INTEGER PRIMARY KEY,
                username          TEXT,
                first_name        TEXT,
                is_premium        INTEGER NOT NULL DEFAULT 0,
                downloads_used    INTEGER NOT NULL DEFAULT 0,
                last_reset_date   TEXT    NOT NULL DEFAULT (date('now')),
                subscription_end  TEXT,
                created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS download_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id  INTEGER NOT NULL,
                platform     TEXT    NOT NULL,
                url          TEXT    NOT NULL,
                success      INTEGER NOT NULL DEFAULT 1,
                downloaded_at TEXT   NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id     INTEGER NOT NULL,
                stars_amount    INTEGER NOT NULL,
                payload         TEXT    NOT NULL,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            );
        """)
    logger.info("Database initialised ✓")


# ─────────────────────────────────────────────
# User helpers
# ─────────────────────────────────────────────

FREE_DAILY_LIMIT = 5


def upsert_user(telegram_id: int, username: str | None, first_name: str | None) -> None:
    """Insert new user or update metadata without overwriting plan info."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (telegram_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name
        """, (telegram_id, username, first_name))


def get_user(telegram_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def _reset_if_new_day(conn, user: dict) -> dict:
    """Reset daily counter when the calendar date has changed."""
    today = str(date.today())
    if user["last_reset_date"] != today:
        conn.execute("""
            UPDATE users
            SET downloads_used = 0, last_reset_date = ?
            WHERE telegram_id = ?
        """, (today, user["telegram_id"]))
        user = dict(conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (user["telegram_id"],)
        ).fetchone())
    return user


def _check_subscription_expired(conn, user: dict) -> dict:
    """Downgrade user if subscription has lapsed."""
    if user["is_premium"] and user["subscription_end"]:
        if user["subscription_end"] < str(date.today()):
            conn.execute("""
                UPDATE users SET is_premium = 0, subscription_end = NULL
                WHERE telegram_id = ?
            """, (user["telegram_id"],))
            user["is_premium"] = 0
            user["subscription_end"] = None
    return user


def can_download(telegram_id: int) -> tuple[bool, dict]:
    """Return (allowed, fresh_user_dict). Handles daily reset & expiry."""
    with get_conn() as conn:
        user = dict(conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone())

        user = _reset_if_new_day(conn, user)
        user = _check_subscription_expired(conn, user)

        if user["is_premium"]:
            return True, user

        allowed = user["downloads_used"] < FREE_DAILY_LIMIT
        return allowed, user


def increment_downloads(telegram_id: int) -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE users SET downloads_used = downloads_used + 1
            WHERE telegram_id = ?
        """, (telegram_id,))


def log_download(telegram_id: int, platform: str, url: str, success: bool = True) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO download_log (telegram_id, platform, url, success)
            VALUES (?, ?, ?, ?)
        """, (telegram_id, platform, url, int(success)))


# ─────────────────────────────────────────────
# Premium / payments
# ─────────────────────────────────────────────

def activate_premium(telegram_id: int, stars_amount: int, payload: str) -> None:
    """Grant one month of premium and record the payment."""
    from dateutil.relativedelta import relativedelta  # type: ignore
    new_expiry = date.today() + relativedelta(months=1)

    with get_conn() as conn:
        conn.execute("""
            UPDATE users
            SET is_premium = 1, subscription_end = ?
            WHERE telegram_id = ?
        """, (str(new_expiry), telegram_id))

        conn.execute("""
            INSERT INTO payments (telegram_id, stars_amount, payload)
            VALUES (?, ?, ?)
        """, (telegram_id, stars_amount, payload))

    logger.info("Premium activated for %s until %s", telegram_id, new_expiry)


def get_stats() -> dict:
    """Quick admin stats."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        premium = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_premium = 1"
        ).fetchone()[0]
        today_dl = conn.execute(
            "SELECT COUNT(*) FROM download_log WHERE date(downloaded_at) = date('now')"
        ).fetchone()[0]
    return {"total_users": total, "premium_users": premium, "downloads_today": today_dl}
