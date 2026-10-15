"""
Long-lived record of the bot's calls, for the leaderboard.

tracked_tokens.json only keeps a coin for ~3 days, which is too short for a
weekly or monthly leaderboard. So every scan, each alerted coin is copied
into a "calls" history that is kept for KEEP_DAYS.

Storage: this lives inside alerted_addresses.json, which the workflow already
caches. That file used to be a plain list of addresses; it's now an object
{"addresses": [...], "calls": {...}, "meta": {...}} and old list-format files
are upgraded automatically on first load. It's done this way on purpose —
adding a new file to the workflow's cache paths would make GitHub treat the
existing cache as a different cache and throw the saved state away.

Every writer must go through load_store()/save_store() so one part of the
bot never overwrites another part's data.
"""

from __future__ import annotations

import json
from pathlib import Path

import config

STORE_PATH = Path("alerted_addresses.json")
TRACKED_PATH = Path("tracked_tokens.json")
KEEP_DAYS = 35
MAX_CALLS = 2500


def _empty() -> dict:
    return {"addresses": [], "calls": {}, "meta": {}}


def load_store() -> dict:
    if not STORE_PATH.exists():
        return _empty()
    try:
        raw = json.loads(STORE_PATH.read_text())
    except (json.JSONDecodeError, ValueError):
        print("[history] alerted_addresses.json was empty or corrupted — starting fresh")
        return _empty()

    store = _empty()
    if isinstance(raw, list):  # old format: just the list of addresses
        store["addresses"] = [str(a) for a in raw]
    elif isinstance(raw, dict):
        store["addresses"] = [str(a) for a in (raw.get("addresses") or [])]
        store["calls"] = raw.get("calls") or {}
        store["meta"] = raw.get("meta") or {}
    return store


def save_store(store: dict):
    STORE_PATH.write_text(json.dumps(store, separators=(",", ":")))


def load_tracked() -> dict:
    if not TRACKED_PATH.exists():
        return {}
    try:
        return json.loads(TRACKED_PATH.read_text())
    except (json.JSONDecodeError, ValueError):
        return {}


def sync_from_tracked(store: dict, tracked: dict, now: float) -> int:
    """Copy every alerted coin's latest numbers into the history. Returns how many were updated.
    Skipped: coins alerted before ATH tracking existed (no peak recorded) and weak alerts,
    which were never pushed to Telegram, so a leaderboard shouldn't count them either."""
    calls = store["calls"]
    updated = 0
    for addr, t in tracked.items():
        if t.get("status") not in ("alerted", "done", "dead") or t.get("legacy"):
            continue
        alert_price, alerted_at = t.get("alert_price"), t.get("alerted_at")
        if not alert_price or not alerted_at:
            continue
        score = t.get("alert_score")
        if score is not None and score < config.MIN_TELEGRAM_SCORE:
            continue

        peak = max((t.get("peak_price") or alert_price) / alert_price, 1.0)
        peak_hours = None
        if t.get("peak_at"):
            peak_hours = max((t["peak_at"] - alerted_at) / 3600, 0)
        last_pct = t.get("last_pct_change")
        calls[addr] = {
            "symbol": t.get("symbol"),
            "name": (t.get("name") or "")[:40],
            "chain": t.get("chain"),
            "alerted_at": int(alerted_at),
            "alert_mcap": t.get("alert_mcap"),
            "peak_mult": round(peak, 3),
            "peak_hours": round(peak_hours, 2) if peak_hours is not None else None,
            "last_pct": round(last_pct, 1) if last_pct is not None else None,
            "status": t["status"],
            "alert_score": score,
            "alert_risk": t.get("alert_risk"),
        }
        updated += 1

    cutoff = now - KEEP_DAYS * 86400
    calls = {a: c for a, c in calls.items() if c.get("alerted_at", 0) >= cutoff}
    if len(calls) > MAX_CALLS:
        newest = sorted(calls.items(), key=lambda kv: kv[1]["alerted_at"], reverse=True)[:MAX_CALLS]
        calls = dict(newest)
    store["calls"] = calls
    return updated
