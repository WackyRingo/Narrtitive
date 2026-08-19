"""
Configuration for the narrative tracker. Runs entirely free with zero
API keys — Telegram is the only optional add-on, and it's free too.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Telegram, optional (free) — leave both blank for console-only alerts ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or None
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or None

# --- Chain scanner thresholds ---
MIN_LIQUIDITY_USD = 5000           # skip tokens too thin to realistically trade
VOLUME_TO_LIQUIDITY_RATIO = 2.0    # 24h volume at least this many x liquidity = unusual turnover
MIN_BUYS_PER_HOUR = 50             # ...or at least this many buy txns in the last hour

# --- Polling ---
# DexScreener's discovery endpoints are free but rate-limited to 60 req/min —
# this script uses 1-2 calls/cycle, so anything above a few seconds is safe.
POLL_INTERVAL_SECONDS = 120
