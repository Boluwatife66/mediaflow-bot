# 🎬 MEDIAFLOW BOT — Setup & Deployment Guide

A production-ready Telegram video downloader bot with Telegram Stars monetisation.

---

## 📁 Project Structure

```
mediaflow_bot/
├── main.py          ← Entry point, registers all handlers
├── handlers.py      ← All user-facing message & button logic
├── payments.py      ← Telegram Stars invoice & webhook handlers
├── downloader.py    ← yt-dlp wrapper (TikTok, IG, FB, YT)
├── database.py      ← SQLite ORM (users, downloads, payments)
├── requirements.txt
└── README.md
```

---

## ⚡ Quick Start (Local)

### 1. Prerequisites

- Python 3.11+
- `ffmpeg` installed (required by yt-dlp for merging audio/video)

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg -y
```

### 2. Clone & install

```bash
git clone <your-repo>
cd mediaflow_bot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Create your bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` → follow the prompts
3. Copy the **HTTP API token**

### 4. Set environment variable

```bash
export BOT_TOKEN="123456:ABC-YourTokenHere"
```

### 5. Run

```bash
python main.py
```

You should see:
```
🚀 MEDIAFLOW BOT is starting…
```

---

## 💎 Enabling Telegram Stars Payments

Stars payments work out of the box — no Stripe or payment provider needed.

1. In **@BotFather**, send `/mybots` → select your bot → **Bot Settings → Payments**
2. Choose **Telegram Stars** (it's free and instant)
3. That's it. The `provider_token` is left as `""` for Stars (handled automatically).

> ⚠️ **Test mode**: In development, payments won't charge real Stars. BotFather provides a test environment automatically when you use the test server.

---

## 🚀 Deployment

### Option A — VPS (Recommended for production)

```bash
# 1. SSH into your server (Ubuntu 22.04 recommended)
ssh user@your-vps-ip

# 2. Install dependencies
sudo apt update && sudo apt install python3.11 python3-pip ffmpeg -y

# 3. Clone your bot
git clone <your-repo> ~/mediaflow_bot
cd ~/mediaflow_bot
pip3 install -r requirements.txt

# 4. Create a systemd service for auto-restart
sudo tee /etc/systemd/system/mediaflow.service > /dev/null <<EOF
[Unit]
Description=MEDIAFLOW Telegram Bot
After=network.target

[Service]
User=$USER
WorkingDirectory=/home/$USER/mediaflow_bot
ExecStart=/usr/bin/python3 main.py
Environment=BOT_TOKEN=your_token_here
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable mediaflow
sudo systemctl start mediaflow

# 5. Check logs
sudo journalctl -u mediaflow -f
```

### Option B — Railway / Render (zero DevOps)

1. Push code to GitHub
2. Create new project on [Railway](https://railway.app) or [Render](https://render.com)
3. Add environment variable: `BOT_TOKEN=<your_token>`
4. Add a `Procfile`:
   ```
   worker: python main.py
   ```
5. Deploy — done!

> **Note**: Add `ffmpeg` buildpack on Railway:  
> Settings → Buildpacks → `https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git`

### Option C — Docker

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t mediaflow .
docker run -d -e BOT_TOKEN=your_token --name mediaflow mediaflow
```

---

## 🔒 Security Checklist

- [x] Rate limiting (10 requests / 60 s per user, in-memory)
- [x] Daily download quota enforced server-side in SQLite
- [x] Subscription expiry checked on every download attempt
- [x] Temp files deleted immediately after sending
- [x] Hourly cleanup job removes orphaned temp files
- [x] All exceptions caught — bot never crashes on user input
- [ ] (Optional) Whitelist specific chat types with `filters`
- [ ] (Optional) Add admin `/stats` command (see below)

---

## 📊 Optional Admin Stats Command

Add this to `handlers.py`:

```python
ADMIN_ID = 123456789   # your Telegram user ID

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
```

And register in `main.py`:
```python
app.add_handler(CommandHandler("stats", stats_handler))
```

---

## 🌱 Scaling Beyond MVP

| Feature | How |
|---|---|
| Webhook instead of polling | `app.run_webhook(...)` + nginx/caddy |
| PostgreSQL | Swap `sqlite3` for `asyncpg` |
| Redis rate limiting | Replace in-memory `_rate_map` |
| Multiple subscription tiers | Add `tier` column to `users` |
| Referral system | Add `referred_by` FK in `users` |
| Analytics dashboard | Read `download_log` → Grafana |

---

## 📋 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Your @BotFather API token |

---

## 🐛 Troubleshooting

**"No output file found after download"**  
→ yt-dlp couldn't find a downloadable stream. The video may be age-restricted or region-locked.

**"Video is too large"**  
→ Telegram Bot API limits file sends to 50 MB. YouTube Shorts / TikTok usually stay under this. For larger files, consider using the Telegram Bot API Local Server.

**Instagram downloads fail**  
→ Instagram heavily rate-limits anonymous downloads. For reliable IG support, provide session cookies via yt-dlp's `--cookies-from-browser` option.

**ffmpeg not found**  
→ `sudo apt install ffmpeg` or `brew install ffmpeg`. yt-dlp requires ffmpeg to merge video+audio streams.
