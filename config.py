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
MIN_PRICE_CHANGE_1H = -5.0         # reject anything down more than this % in the last hour —
                                    # "high volume" while crashing isn't the signal we want
MAX_TOKEN_AGE_HOURS = 24           # ignore tokens older than this (also catches old tokens that
                                    # only just got a paid boost, which isn't the same as being new)
ALLOWED_CHAINS = ["solana", "bsc", "ethereum", "base"]
# Empty list = allow every chain DexScreener returns. "robinhood" (Robinhood's own
# L2, launched July 2026) is deliberately left out by default — legitimate chain,
# but very new and currently almost all memecoin speculation. Add it here to include it.

# --- Tracking & outcome checkpoints ---
# After an alert fires, the scanner checks back in at each of these hour marks
# and records what actually happened — an honest track record instead of a
# one-off claim. Tokens that DON'T qualify yet also get re-checked on this same
# cadence, up to MAX_TOKEN_AGE_HOURS, to catch ones that build momentum later.
CHECKPOINT_HOURS = [1, 6, 24]

# --- Polling ---
# DexScreener's discovery endpoints are free but rate-limited to 60 req/min —
# this script uses a small, batched number of calls per cycle either way.
POLL_INTERVAL_SECONDS = 120
