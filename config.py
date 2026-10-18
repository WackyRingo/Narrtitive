"""
Configuration for the narrative tracker. Runs entirely free with zero
API keys — Telegram and the Solana risk check are optional add-ons,
and both are free too.
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

# A coin is "dead" — and gets one final message, then no more checking — once, for
# DEAD_CONFIRMATIONS scans in a row (so one bad reading can't kill it), its price is
# down DEAD_DROP_FROM_ALERT_PCT or more from the alert, its pool has drained below
# DEAD_MIN_LIQUIDITY_USD, or DexScreener no longer lists the pair.
DEAD_DROP_FROM_ALERT_PCT = -90
DEAD_MIN_LIQUIDITY_USD = 1000
DEAD_CONFIRMATIONS = 2

# Check-ins and death messages for coins that ran at least this many x above the alert
# price come with a PNL-style image card instead of plain text.
PNL_CARD_MIN_MULT = 2.0

# --- Leaderboard ---
# Ranks the bot's own calls by how high they ran, with hit-rate stats. One message in the chat is
# kept up to date (and pinned), and on demand you can type /lb (or /lb 24h, /lb 7d, /lb 30d,
# /lb all) for a period, or /stats to see which entry conditions actually predicted results.
LEADERBOARD_AUTOPOST = True    # keep one leaderboard message updated in place
LEADERBOARD_PIN = True         # ...and pinned (works in a private chat; in a group the bot must be admin)
LEADERBOARD_PERIOD = "7d"      # period for the pinned board and for a bare /lb
LEADERBOARD_TOP_N = 10
LEADERBOARD_UPDATE_MINUTES = 30

# --- Keeping the chat quiet ---
EDIT_IN_PLACE = True           # check-ins/deaths edit the coin's original alert instead of new messages
QUIET_FOLLOWUPS = True         # standalone follow-ups arrive without a phone buzz
CARD_NOTIFY = True             # ...but an image card for a 2x+ runner does buzz
LOUD_DEATH_SCORE = 80          # a call that scored this high and then died also gets a short fresh note
WAVE_COLLAPSE = True           # 3+ coins sharing a theme word in one batch -> one alert + one digest
WAVE_MIN = 3

# --- Filters beyond the activity thresholds ---
DROP_RUGGED = True             # don't alert coins Solana Tracker already flags as rugged
DROP_HONEYPOTS = True          # don't alert coins GoPlus says can't be sold
# Off by default. Extreme moves can be coordinated pumps, but there's no evidence yet that they do worse —
# check /stats first. Set to a number (e.g. 500 for +500% in an hour, 0.90 for 90% buys) to cap them.
MAX_PRICE_CHANGE_1H = None
MAX_BUY_RATIO = None

# --- Polling ---
# DexScreener's discovery endpoints are free but rate-limited to 60 req/min —
# this script uses a small, batched number of calls per cycle either way.
POLL_INTERVAL_SECONDS = 120
