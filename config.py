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

# --- Solana Tracker, optional (free tier: 2,500 requests/month, no card) ---
# Powers the Security line: rug risk score, snipers, bundlers, insiders. Solana only.
# Leave blank and alerts just skip straight to the Bubblemaps link instead.
SOLANA_TRACKER_API_KEY = os.getenv("SOLANA_TRACKER_API_KEY") or None

# --- Chain scanner thresholds ---
MIN_LIQUIDITY_USD = 5000           # skip tokens too thin to realistically trade
VOLUME_TO_LIQUIDITY_RATIO = 2.0    # 24h volume at least this many x liquidity = unusual turnover
MIN_BUYS_PER_HOUR = 50             # ...or at least this many buy txns in the last hour
MIN_TELEGRAM_SCORE = 50            # only push to Telegram at/above this activity score (Moderate+);
                                    # everything still prints to the console/Actions log regardless
PULLBACK_ALERT_THRESHOLD = 0.30    # warn once a token has fallen this much from its post-alert peak
MIN_PRICE_CHANGE_1H = -5.0         # reject anything down more than this % in the last hour —
                                    # "high volume" while crashing isn't the signal we want
MIN_BUY_RATIO = 0.45               # reject if sells already outnumber buys this much, even when
                                    # price is still nominally up — catches order flow flipping
                                    # before price has caught up to it
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
CHECKPOINT_HOURS = [1, 6, 24, 72]

# --- Polling ---
# DexScreener's discovery endpoints are free but rate-limited to 60 req/min —
# this script uses a small, batched number of calls per cycle either way.
POLL_INTERVAL_SECONDS = 120
