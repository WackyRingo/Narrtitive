"""
A Phanes-style leaderboard of the bot's own calls: stats for a period, then the
best calls ranked by how high they ran (ATH multiple vs the alert price).

Three ways it shows up:
  - automatically once a day (LEADERBOARD_AUTOPOST, at LEADERBOARD_HOUR_UTC),
  - on demand: type /lb in the Telegram chat — /lb 24h, /lb 7d, /lb 30d, /lb all —
    and the next scan replies (scans can run late, so give it a while),
  - printed in the run log.

Ranking by ATH flatters a call list, since a coin that ran 5x and then dumped
still ranks high. So the stats block also says how many finished calls ended
above their alert price and how many died. ATH here is the highest price seen
at our scans, so a spike that rose and fell between two scans is missed.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone

import requests

import config
import history

PERIODS = {
    "24h": ("24h", 24), "1d": ("24h", 24),
    "7d": ("7d", 168), "1w": ("7d", 168),
    "30d": ("30d", 720), "1m": ("30d", 720),
    "all": ("all", None),
}
TITLES = {"24h": "last 24 hours", "7d": "last 7 days", "30d": "last 30 days", "all": "all tracked calls"}
CHAIN = {"solana": "SOL", "bsc": "BSC", "ethereum": "ETH", "base": "BASE"}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def parse_period(arg: str):
    """(label, hours) for text like '7d' — falls back to the configured default period."""
    key = (arg or "").strip().lower()
    return PERIODS.get(key) or PERIODS.get(str(config.LEADERBOARD_PERIOD).lower(), PERIODS["7d"])


def _fmt_cap(v) -> str:
    if v is None:
        return "?"
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.2f}M"
    if v >= 1e3:
        return f"${v / 1e3:.1f}K"
    return f"${v:.0f}"


def _is_finished(c: dict, now: float) -> bool:
    if c.get("status") in ("dead", "done"):
        return True
    return (now - c.get("alerted_at", now)) > (max(config.CHECKPOINT_HOURS) + 6) * 3600


def build(calls: dict, label: str, hours, now: float, top_n: int):
    """The leaderboard text for a period, or None if there are no calls in it."""
    items = list(calls.values())
    if hours is not None:
        cutoff = now - hours * 3600
        items = [c for c in items if c.get("alerted_at", 0) >= cutoff]
    if not items:
        return None

    n = len(items)
    peaks = [c["peak_mult"] for c in items]
    finished = [c for c in items if _is_finished(c, now)]
    hit2 = sum(1 for x in peaks if x >= 2)
    up = sum(1 for c in finished if (c.get("last_pct") or 0) > 0)
    dead = sum(1 for c in items if c.get("status") == "dead")

    lines = [
        f"🏆 LEADERBOARD · {TITLES.get(label, label)}",
        "",
        "📊 Stats",
        f"├ Calls     {n} ({len(finished)} finished)",
        f"├ Hit rate  {hit2 / n:.0%} reached 2x+",
        f"├ Median    {statistics.median(peaks):.1f}x",
        f"├ Avg       {sum(peaks) / n:.1f}x",
        f"└ Ended up  {up}/{len(finished)} finished · 💀 {dead} dead" if finished
        else f"└ Ended up  — · 💀 {dead} dead",
        "",
    ]

    ranked = sorted(items, key=lambda c: c["peak_mult"], reverse=True)[:top_n]
    for i, c in enumerate(ranked, 1):
        mult = c["peak_mult"]
        mult_s = f"{mult:.0f}x" if mult >= 10 else f"{mult:.1f}x"
        entry = c.get("alert_mcap")
        route = f"{_fmt_cap(entry)} → {_fmt_cap(entry * mult)}" if entry else ""
        pct = c.get("last_pct")
        if c.get("status") == "dead":
            state = "💀 dead"
        elif pct is None:
            state = ""
        elif c.get("status") == "done":
            state = f"ended {pct:+.0f}%"
        else:
            state = f"now {pct:+.0f}%"
        head = f"{MEDALS.get(i, f'{i}.')} ${c.get('symbol')} [{mult_s}] {CHAIN.get(c.get('chain'), '')}".rstrip()
        detail = " · ".join(p for p in (route, state) if p)
        lines.append(f"{head}" + (f"  —  {detail}" if detail else ""))

    lines += ["", "ATH = highest price seen at scan times (can undercount fast spikes)."]
    return "\n".join(lines)


def _fetch_updates(offset):
    params = {"timeout": 0, "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates", params=params, timeout=15
        )
    except requests.exceptions.RequestException as e:
        print(f"[leaderboard] couldn't check Telegram for commands: {e}")
        return []
    if resp.status_code != 200:
        print(f"[leaderboard] getUpdates failed: {resp.status_code} {resp.text[:150]}")
        return []
    return resp.json().get("result") or []


def handle_commands(store: dict, now: float, send, fetch=_fetch_updates):
    """Answer /lb and /leaderboard sent in the configured chat since the last scan."""
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return
    meta = store["meta"]
    last = meta.get("last_update_id")
    for update in fetch(last + 1 if last else None):
        meta["last_update_id"] = max(meta.get("last_update_id", 0), update.get("update_id", 0))
        msg = update.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
            continue  # only answer the chat this bot is set up for
        cmd, _, arg = (msg.get("text") or "").strip().partition(" ")
        if cmd.split("@")[0].lower() not in ("/lb", "/leaderboard"):
            continue
        label, hours = parse_period(arg)
        text = build(store["calls"], label, hours, now, config.LEADERBOARD_TOP_N)
        send(text or f"No calls in the {TITLES.get(label, label)} yet.")


def maybe_autopost(store: dict, now: float, send):
    """Post the leaderboard once a day, at the first scan after LEADERBOARD_HOUR_UTC."""
    if not config.LEADERBOARD_AUTOPOST:
        return
    moment = datetime.fromtimestamp(now, tz=timezone.utc)
    today = moment.strftime("%Y-%m-%d")
    if moment.hour < config.LEADERBOARD_HOUR_UTC or store["meta"].get("last_post_date") == today:
        return
    label, hours = parse_period(config.LEADERBOARD_PERIOD)
    text = build(store["calls"], label, hours, now, config.LEADERBOARD_TOP_N)
    if text:
        send(text)
        store["meta"]["last_post_date"] = today


def run_housekeeping(now=None, send=None):
    """Called once per scan: update the history, answer any /lb commands, do the daily post."""
    now = now if now is not None else time.time()
    if send is None:
        import alerts
        send = alerts._send
    store = history.load_store()
    try:
        history.sync_from_tracked(store, history.load_tracked(), now)
        try:
            handle_commands(store, now, send)
        except Exception as e:
            print(f"[leaderboard] command handling failed: {e}")
        try:
            maybe_autopost(store, now, send)
        except Exception as e:
            print(f"[leaderboard] daily post failed: {e}")
    finally:
        history.save_store(store)
