"""
Free primary detector: watches DexScreener's public "latest token
profiles" and "latest boosted tokens" feeds for brand-new tokens, then
tracks each one over time — re-checking ones that don't qualify yet in
case they build momentum later, and checking in on already-alerted
tokens at set intervals so there's an honest record of what actually
happened afterward, not just a one-off claim. No Twitter, no API key,
no cost — just DexScreener's free, keyless endpoints.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import config

BASE_URL = "https://api.dexscreener.com"
TRACKED_PATH = Path("tracked_tokens.json")


def _load_tracked() -> dict:
    if TRACKED_PATH.exists():
        return json.loads(TRACKED_PATH.read_text())
    return {}


def _save_tracked(tracked: dict):
    if len(tracked) > 3000:
        newest = sorted(tracked.items(), key=lambda kv: kv[1].get("first_seen", 0), reverse=True)
        tracked = dict(newest[:3000])
    TRACKED_PATH.write_text(json.dumps(tracked))


def get_latest_profiles() -> list[dict]:
    resp = requests.get(f"{BASE_URL}/token-profiles/latest/v1", timeout=10)
    if resp.status_code != 200:
        print(f"[chain_scanner] profiles fetch failed: {resp.status_code}")
        return []
    data = resp.json()
    return data if isinstance(data, list) else data.get("data", [])


def get_latest_boosts() -> list[dict]:
    resp = requests.get(f"{BASE_URL}/token-boosts/latest/v1", timeout=10)
    if resp.status_code != 200:
        print(f"[chain_scanner] boosts fetch failed: {resp.status_code}")
        return []
    data = resp.json()
    return data if isinstance(data, list) else data.get("data", [])


def get_pairs_batch(addresses: list[str]) -> dict[str, dict]:
    """Fetch live pair data for many addresses at once, 30 per call (DexScreener's limit)."""
    results = {}
    for i in range(0, len(addresses), 30):
        batch = addresses[i:i + 30]
        resp = requests.get(f"{BASE_URL}/latest/dex/tokens/{','.join(batch)}", timeout=15)
        if resp.status_code != 200:
            print(f"[chain_scanner] batch pair fetch failed: {resp.status_code}")
            continue
        for pair in resp.json().get("pairs") or []:
            addr = (pair.get("baseToken") or {}).get("address")
            if not addr:
                continue
            liq = (pair.get("liquidity") or {}).get("usd", 0) or 0
            existing = results.get(addr)
            if not existing or liq > (existing.get("liquidity") or {}).get("usd", 0):
                results[addr] = pair
    return results


def _pair_age_hours(pair: dict) -> float | None:
    created_ms = pair.get("pairCreatedAt")
    if not created_ms:
        return None
    created = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600


def _safe_float(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _is_unusually_active(pair: dict) -> bool:
    if config.ALLOWED_CHAINS and pair.get("chainId") not in config.ALLOWED_CHAINS:
        return False

    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    if liquidity < config.MIN_LIQUIDITY_USD:
        return False

    age_hours = _pair_age_hours(pair)
    if age_hours is not None and age_hours > config.MAX_TOKEN_AGE_HOURS:
        return False

    price_change_1h = (pair.get("priceChange") or {}).get("h1")
    if price_change_1h is not None and price_change_1h < config.MIN_PRICE_CHANGE_1H:
        return False  # already falling — heavy volume while dropping isn't the signal we want

    txns_1h = (pair.get("txns") or {}).get("h1") or {}
    buys_1h = txns_1h.get("buys") or 0
    sells_1h = txns_1h.get("sells") or 0
    total_1h = buys_1h + sells_1h
    if total_1h > 0 and (buys_1h / total_1h) < config.MIN_BUY_RATIO:
        return False  # sells already outpacing buys, even if price hasn't caught up to it yet

    volume_24h = (pair.get("volume") or {}).get("h24") or 0

    if liquidity > 0 and (volume_24h / liquidity) >= config.VOLUME_TO_LIQUIDITY_RATIO:
        return True
    if buys_1h >= config.MIN_BUYS_PER_HOUR:
        return True
    return False


def generate_quick_read(token: dict) -> str:
    """Free, rule-based read on the numbers — no API call, no cost."""
    notes = []

    vol, liq = token.get("volume_24h") or 0, token.get("liquidity_usd") or 0
    if liq > 0:
        ratio = vol / liq
        if ratio >= 5:
            notes.append(
                f"Volume is {ratio:.1f}x liquidity — very high turnover for a pool this "
                "size; can mean real demand or a thin pool being pushed hard."
            )
        elif ratio >= config.VOLUME_TO_LIQUIDITY_RATIO:
            notes.append(f"Volume is {ratio:.1f}x liquidity — trading harder than its size usually would.")

    buys, sells = token.get("buys_1h"), token.get("sells_1h")
    if buys is not None and sells is not None and (buys + sells) > 0:
        pct_buy = buys / (buys + sells) * 100
        notes.append(f"{pct_buy:.0f}% of the last hour's trades were buys ({buys} buys vs {sells} sells).")

    if token.get("age_hours") is not None and token["age_hours"] < 2:
        notes.append(f"Only {token['age_hours']:.1f}h old — very early, which cuts both ways.")

    notes.append(
        "No holder or rug-check data yet (that's the rug-filter module, still to build) — "
        "treat this as a lead to check manually, not a signal to act on."
    )
    return " ".join(notes)


def compute_activity_score(token: dict) -> int:
    """
    0-100 composite of how strong the raw activity looks right now —
    turnover relative to pool size, buy pressure, 1h momentum, and pool
    size itself. This is NOT a prediction and NOT a safety check — it
    says nothing about holders, contract risk, or legitimacy. A
    well-funded rug can score just as high as a real mover.
    """
    liq = token.get("liquidity_usd") or 0
    vol = token.get("volume_24h") or 0
    buys = token.get("buys_1h") or 0
    sells = token.get("sells_1h") or 0
    price_change_1h = token.get("price_change_1h") or 0

    vol_liq_ratio = (vol / liq) if liq > 0 else 0
    buy_ratio = (buys / (buys + sells)) if (buys + sells) > 0 else 0.5

    score = 0
    score += min(vol_liq_ratio / 10, 1) * 30                              # turnover, caps at 10x
    score += min(max(buy_ratio - 0.45, 0) / 0.55, 1) * 25                 # buy pressure, caps at 100% buys
    score += min(max(price_change_1h, 0) / 200, 1) * 25                   # momentum, caps at +200%/1h
    score += min(liq / 50000, 1) * 20                                     # pool size, caps at $50k+
    return round(score)


def _score_label(score: int) -> str:
    if score >= 75:
        return "Strong"
    if score >= 50:
        return "Moderate"
    return "Weak"


def _token_snapshot(pair: dict) -> dict:
    base = pair.get("baseToken", {})
    snap = {
        "type": "alert",
        "name": base.get("name"),
        "symbol": base.get("symbol"),
        "chain": pair.get("chainId"),
        "address": base.get("address"),
        "price_usd": pair.get("priceUsd"),
        "price_change_1h": (pair.get("priceChange") or {}).get("h1"),
        "price_change_24h": (pair.get("priceChange") or {}).get("h24"),
        "market_cap": pair.get("marketCap"),
        "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
        "volume_24h": (pair.get("volume") or {}).get("h24"),
        "buys_1h": (pair.get("txns") or {}).get("h1", {}).get("buys"),
        "sells_1h": (pair.get("txns") or {}).get("h1", {}).get("sells"),
        "age_hours": _pair_age_hours(pair),
        "url": pair.get("url"),
    }
    snap["activity_score"] = compute_activity_score(snap)
    snap["activity_label"] = _score_label(snap["activity_score"])
    return snap


def _next_due_checkpoint(t: dict, now: float) -> float | None:
    hours_since_alert = (now - t.get("alerted_at", now)) / 3600
    done = set(t.get("checkpoints_done", []))
    for cp in sorted(config.CHECKPOINT_HOURS):
        if cp not in done and hours_since_alert >= cp:
            return cp
    return None


def scan_for_active_new_tokens() -> list[dict]:
    """
    Each cycle: finds brand-new tokens and alerts on ones that already
    qualify; re-checks tokens that didn't qualify yet in case they've
    built momentum since; and checks in on already-alerted tokens at
    set intervals to record what actually happened. Returns a list of
    dicts tagged "type": "alert" or "checkpoint".
    """
    tracked = _load_tracked()
    now = time.time()
    outputs = []

    candidates = get_latest_profiles() + get_latest_boosts()
    for c in candidates:
        addr = c.get("tokenAddress")
        if addr and addr not in tracked:
            tracked[addr] = {"first_seen": now, "status": "watching", "chain": c.get("chainId")}

    still_watching = [
        addr for addr, t in tracked.items()
        if t.get("status") == "watching" and (now - t["first_seen"]) / 3600 <= config.MAX_TOKEN_AGE_HOURS
    ]
    due_for_checkpoint = [
        addr for addr, t in tracked.items()
        if t.get("status") == "alerted" and _next_due_checkpoint(t, now) is not None
    ]
    to_fetch = list(set(still_watching + due_for_checkpoint))
    pairs = get_pairs_batch(to_fetch) if to_fetch else {}

    for addr in still_watching:
        pair = pairs.get(addr)
        if not pair or not _is_unusually_active(pair):
            continue
        snap = _token_snapshot(pair)
        snap["quick_read"] = generate_quick_read(snap)
        outputs.append(snap)
        tracked[addr].update({
            "status": "alerted",
            "alerted_at": now,
            "alert_price": _safe_float(pair.get("priceUsd")),
            "name": snap["name"],
            "symbol": snap["symbol"],
            "checkpoints_done": [],
        })

    for addr in due_for_checkpoint:
        pair = pairs.get(addr)
        t = tracked[addr]
        due_hours = _next_due_checkpoint(t, now)
        if not pair:
            t["checkpoints_done"] = t.get("checkpoints_done", []) + [due_hours]
            continue

        current_price = _safe_float(pair.get("priceUsd"))
        alert_price = t.get("alert_price")
        pct_change = None
        if current_price is not None and alert_price:
            pct_change = (current_price - alert_price) / alert_price * 100

        outputs.append({
            "type": "checkpoint",
            "name": t.get("name"),
            "symbol": t.get("symbol"),
            "chain": t.get("chain"),
            "hours": due_hours,
            "pct_change": pct_change,
            "market_cap": pair.get("marketCap"),
            "url": pair.get("url"),
        })
        t["checkpoints_done"] = t.get("checkpoints_done", []) + [due_hours]
        if pct_change is not None:
            t["last_pct_change"] = pct_change

    max_checkpoint = max(config.CHECKPOINT_HOURS)
    tracked = {
        addr: t for addr, t in tracked.items()
        if (t.get("status") == "watching" and (now - t["first_seen"]) / 3600 <= config.MAX_TOKEN_AGE_HOURS)
        or (t.get("status") == "alerted" and (now - t.get("alerted_at", now)) / 3600 <= max_checkpoint + 6)
    }

    _save_tracked(tracked)
    return outputs


def track_record_summary() -> str | None:
    """An honest scorecard: of alerts that reached their final checkpoint, how many were up?"""
    tracked = _load_tracked()
    max_checkpoint = max(config.CHECKPOINT_HOURS)
    finals = [
        t for t in tracked.values()
        if t.get("status") == "alerted"
        and max_checkpoint in t.get("checkpoints_done", [])
        and t.get("last_pct_change") is not None
    ]
    if not finals:
        return None
    up = sum(1 for t in finals if t["last_pct_change"] > 0)
    avg = sum(t["last_pct_change"] for t in finals) / len(finals)
    return f"Track record: {up}/{len(finals)} alerts were up {max_checkpoint:.0f}h later (avg {avg:+.0f}%)."
