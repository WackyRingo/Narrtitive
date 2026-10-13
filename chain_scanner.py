"""
Free primary detector: watches DexScreener's public "latest token
profiles" and "latest boosted tokens" feeds for brand-new tokens, then
tracks each one over time — re-checking ones that don't qualify yet in
case they build momentum later, and checking in on already-alerted
tokens at set intervals so there's an honest record of what actually
happened afterward, not just a one-off claim. No Twitter, no API key,
no cost — just DexScreener's free, keyless endpoints.

Resilient by design: every network call catches its own failures and
degrades to "nothing this cycle" instead of crashing, and tracking
state is saved in a finally block so a crash partway through a cycle
still keeps whatever progress was made rather than losing it.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import config
import rug_filter

BASE_URL = "https://api.dexscreener.com"
TRACKED_PATH = Path("tracked_tokens.json")
PERMANENT_SEEN_PATH = Path("alerted_addresses.json")  # never pruned — belt and suspenders against repeats
REQUEST_TIMEOUT = 15


def _load_tracked() -> dict:
    if TRACKED_PATH.exists():
        try:
            return json.loads(TRACKED_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            print("[chain_scanner] tracked_tokens.json was empty or corrupted — starting fresh")
    return {}


def _save_tracked(tracked: dict):
    if len(tracked) > 3000:
        newest = sorted(tracked.items(), key=lambda kv: kv[1].get("first_seen", 0), reverse=True)
        tracked = dict(newest[:3000])
    TRACKED_PATH.write_text(json.dumps(tracked))


def _load_permanent_seen() -> set:
    if PERMANENT_SEEN_PATH.exists():
        try:
            return set(json.loads(PERMANENT_SEEN_PATH.read_text()))
        except (json.JSONDecodeError, ValueError):
            print("[chain_scanner] alerted_addresses.json was empty or corrupted — starting fresh")
    return set()


def _save_permanent_seen(addresses: set):
    PERMANENT_SEEN_PATH.write_text(json.dumps(sorted(addresses)))


def get_latest_profiles() -> list[dict]:
    try:
        resp = requests.get(f"{BASE_URL}/token-profiles/latest/v1", timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        print(f"[chain_scanner] profiles fetch failed (network error): {e}")
        return []
    if resp.status_code != 200:
        print(f"[chain_scanner] profiles fetch failed: {resp.status_code}")
        return []
    data = resp.json()
    return data if isinstance(data, list) else data.get("data", [])


def get_latest_boosts() -> list[dict]:
    try:
        resp = requests.get(f"{BASE_URL}/token-boosts/latest/v1", timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        print(f"[chain_scanner] boosts fetch failed (network error): {e}")
        return []
    if resp.status_code != 200:
        print(f"[chain_scanner] boosts fetch failed: {resp.status_code}")
        return []
    data = resp.json()
    return data if isinstance(data, list) else data.get("data", [])


def _fetch_pairs(batch: list, results: dict, failed: set):
    """One DexScreener lookup. A 400/404 on a multi-address batch usually means one bad
    address poisoned the whole call, so split it in half and retry to isolate it — an
    address that 404s on its own is simply "not found". Network errors and other statuses
    mark the whole batch as failed (no splitting, so an outage can't snowball into dozens
    of slow calls)."""
    try:
        resp = requests.get(f"{BASE_URL}/latest/dex/tokens/{','.join(batch)}", timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        print(f"[chain_scanner] batch pair fetch failed (network error): {e}")
        failed.update(batch)
        return

    if resp.status_code in (400, 404):
        if len(batch) > 1:
            mid = len(batch) // 2
            _fetch_pairs(batch[:mid], results, failed)
            _fetch_pairs(batch[mid:], results, failed)
        else:
            print(f"[chain_scanner] {batch[0]} not found ({resp.status_code})")
        return

    if resp.status_code != 200:
        print(f"[chain_scanner] batch pair fetch failed: {resp.status_code} — body: {resp.text[:200]}")
        failed.update(batch)
        return

    try:
        pairs = resp.json().get("pairs") or []
    except ValueError:
        print("[chain_scanner] batch pair fetch returned invalid JSON")
        failed.update(batch)
        return

    for pair in pairs:
        addr = (pair.get("baseToken") or {}).get("address")
        if not addr:
            continue
        liq = (pair.get("liquidity") or {}).get("usd", 0) or 0
        existing = results.get(addr)
        if not existing or liq > (existing.get("liquidity") or {}).get("usd", 0):
            results[addr] = pair


def get_pairs_batch(addresses: list) -> tuple:
    """Fetch live pair data for many addresses, 30 per call (DexScreener's limit).
    Returns (pair_by_address, failed_addresses) — "failed" means we couldn't reach
    DexScreener for those, which is different from the token simply not being found."""
    results, failed = {}, set()
    for i in range(0, len(addresses), 30):
        _fetch_pairs(addresses[i:i + 30], results, failed)
    return results, failed


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
    score += min(vol_liq_ratio / 10, 1) * 30
    score += min(max(buy_ratio - 0.45, 0) / 0.55, 1) * 25
    score += min(max(price_change_1h, 0) / 200, 1) * 25
    score += min(liq / 50000, 1) * 20
    return round(score)


def _score_label(score: int) -> str:
    if score >= 75:
        return "Strong"
    if score >= 50:
        return "Moderate"
    return "Weak"


def generate_quick_read(token: dict, has_rug_check: bool = False) -> str:
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

    if has_rug_check:
        notes.append(
            "See the Security line above for holder/sniper/bundler signals — a real check now, "
            "still not a guarantee. Clearing it narrows out known red flags, it doesn't confirm safety."
        )
    elif token.get("chain") == "solana":
        notes.append(
            "Rug check returned nothing for this token (API unavailable or over quota) — "
            "treat this as a lead to check manually, not a signal to act on."
        )
    else:
        notes.append(
            "No rug-check data for this chain yet — treat this as a lead to check manually, "
            "not a signal to act on."
        )
    return " ".join(notes)


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


def _lookup(pairs: dict, pairs_ci: dict, addr: str):
    return pairs.get(addr) or pairs_ci.get(addr.lower())


def _due_checkpoints(t: dict, now: float) -> list:
    hours_since_alert = (now - t.get("alerted_at", now)) / 3600
    done = set(t.get("checkpoints_done", []))
    return [cp for cp in sorted(config.CHECKPOINT_HOURS) if cp not in done and hours_since_alert >= cp]


def _peak_info(t: dict):
    """(peak multiple vs alert price, hours after alert it was seen) from a tracked record.
    The peak is the highest price seen at our scans, so a spike that rose and fell between
    two scans is missed and the true ATH can be higher."""
    alert_price, peak = t.get("alert_price"), t.get("peak_price")
    if not alert_price or not peak:
        return None, None
    mult = max(peak / alert_price, 1.0)
    peak_hours = None
    if t.get("peak_at") and t.get("alerted_at"):
        peak_hours = max((t["peak_at"] - t["alerted_at"]) / 3600, 0)
    return mult, peak_hours


def _update_alerted(t: dict, pair, fetch_failed: bool, now: float):
    """Refresh one alerted token: track its peak, decide if it's dead, and emit a check-in
    if one is due. Returns at most one output dict (a "dead" or "checkpoint" message)."""
    if fetch_failed:
        return None  # couldn't reach DexScreener — don't count it against the token

    if "peak_price" not in t:
        t["legacy"] = True  # alerted before ATH tracking existed — remembered, so it stays legacy
    legacy = t.get("legacy", False)
    alert_price = t.get("alert_price")
    price = _safe_float(pair.get("priceUsd")) if pair else None
    liquidity = (pair.get("liquidity") or {}).get("usd") if pair else None
    market_cap = pair.get("marketCap") if pair else None

    t.setdefault("peak_price", alert_price)
    t.setdefault("peak_at", t.get("alerted_at", now))
    if price is not None and alert_price:
        if price > (t.get("peak_price") or 0):
            t["peak_price"], t["peak_at"] = price, now
        t["last_pct_change"] = (price - alert_price) / alert_price * 100
    if market_cap is not None:
        t["last_market_cap"] = market_cap
    if pair and pair.get("url"):
        t["url"] = pair["url"]

    reason = None
    if pair is None or price is None:
        reason = "pair no longer found"
    elif alert_price and price <= alert_price * (1 + config.DEAD_DROP_FROM_ALERT_PCT / 100):
        reason = f"price down {abs(config.DEAD_DROP_FROM_ALERT_PCT):.0f}%+ from the alert"
    elif liquidity is not None and liquidity < config.DEAD_MIN_LIQUIDITY_USD:
        reason = "liquidity drained"
    t["dead_strikes"] = t.get("dead_strikes", 0) + 1 if reason else 0

    peak_mult, peak_hours = _peak_info(t)
    base = {
        "name": t.get("name"), "symbol": t.get("symbol"), "chain": t.get("chain"),
        "alert_score": t.get("alert_score"), "alert_risk": t.get("alert_risk"),
        # legacy coins have no recorded peak, so show ATH as unknown rather than a misleading 1.0x
        "peak_mult": None if legacy else peak_mult,
        "peak_hours": None if legacy else peak_hours,
        "url": t.get("url"),
    }

    if t["dead_strikes"] >= config.DEAD_CONFIRMATIONS:
        t["status"] = "dead"
        t["died_at"] = now
        if legacy:
            return None  # old alert, no peak history — retire it quietly instead of a burst of messages
        return {
            **base, "type": "dead", "reason": reason,
            "pct_change": t.get("last_pct_change"),
            "market_cap": t.get("last_market_cap"), "liquidity_usd": liquidity,
            "lifetime_hours": (now - t.get("alerted_at", now)) / 3600,
        }

    if price is None:
        return None  # wait for a clean reading before sending a check-in

    due = _due_checkpoints(t, now)
    if not due:
        return None
    t["checkpoints_done"] = t.get("checkpoints_done", []) + due
    if max(config.CHECKPOINT_HOURS) in t["checkpoints_done"]:
        t["status"] = "done"
    return {
        **base, "type": "checkpoint", "hours": max(due),
        "pct_change": t.get("last_pct_change"), "market_cap": market_cap,
    }


def scan_for_active_new_tokens() -> list[dict]:
    """
    Each cycle: finds brand-new tokens and alerts on ones that already qualify; re-checks
    tokens that didn't qualify yet in case they've built momentum since; and refreshes every
    alerted token — tracking its peak, sending check-ins at the set hour marks, and retiring
    it with a final "dead" message once it has collapsed. Returns dicts tagged "type":
    "alert", "checkpoint", or "dead".

    Whatever progress is made gets saved in the finally block even if something
    unexpected fails partway through this function.
    """
    tracked = _load_tracked()
    permanent_seen = _load_permanent_seen()
    now = time.time()
    outputs = []
    print(f"[chain_scanner] state loaded: {len(tracked)} tracked, {len(permanent_seen)} permanently seen")

    try:
        candidates = get_latest_profiles() + get_latest_boosts()
        for c in candidates:
            addr = c.get("tokenAddress")
            if addr and addr not in tracked and addr not in permanent_seen:
                tracked[addr] = {"first_seen": now, "status": "watching", "chain": c.get("chainId")}

        still_watching = [
            addr for addr, t in tracked.items()
            if t.get("status") == "watching" and (now - t["first_seen"]) / 3600 <= config.MAX_TOKEN_AGE_HOURS
        ]
        alerted_alive = [addr for addr, t in tracked.items() if t.get("status") == "alerted"]
        print(f"[chain_scanner] checking {len(still_watching)} watching + {len(alerted_alive)} alerted tokens")

        to_fetch = list(set(still_watching + alerted_alive))
        pairs, failed = get_pairs_batch(to_fetch) if to_fetch else ({}, set())
        pairs_ci = {k.lower(): v for k, v in pairs.items()}

        for addr in still_watching:
            try:
                pair = _lookup(pairs, pairs_ci, addr)
                if not pair or not _is_unusually_active(pair):
                    continue
                snap = _token_snapshot(pair)
                snap["rug_check"] = rug_filter.get_rug_check(snap["chain"], snap["address"])
                snap["quick_read"] = generate_quick_read(snap, has_rug_check=snap["rug_check"] is not None)
                outputs.append(snap)
                alert_price = _safe_float(pair.get("priceUsd"))
                tracked[addr].update({
                    "status": "alerted",
                    "alerted_at": now,
                    "alert_price": alert_price,
                    "alert_score": snap["activity_score"],
                    "alert_risk": (snap.get("rug_check") or {}).get("score"),
                    "peak_price": alert_price,
                    "peak_at": now,
                    "dead_strikes": 0,
                    "url": snap.get("url"),
                    "name": snap["name"],
                    "symbol": snap["symbol"],
                    "checkpoints_done": [],
                })
                permanent_seen.add(addr)
            except Exception as e:
                print(f"[chain_scanner] error evaluating {addr}: {e}")

        for addr in alerted_alive:
            try:
                out = _update_alerted(tracked[addr], _lookup(pairs, pairs_ci, addr), addr in failed, now)
                if out:
                    outputs.append(out)
            except Exception as e:
                print(f"[chain_scanner] error updating {addr}: {e}")

        max_checkpoint = max(config.CHECKPOINT_HOURS)
        tracked = {
            addr: t for addr, t in tracked.items()
            if (t.get("status") == "watching" and (now - t["first_seen"]) / 3600 <= config.MAX_TOKEN_AGE_HOURS)
            or (t.get("status") in ("alerted", "done", "dead")
                and (now - t.get("alerted_at", now)) / 3600 <= max_checkpoint + 6)
        }
    except Exception as e:
        print(f"[chain_scanner] scan cycle error: {e}")
    finally:
        _save_tracked(tracked)
        _save_permanent_seen(permanent_seen)

    return outputs


def track_record_summary() -> str | None:
    """An honest scorecard over alerts that have finished (died, or ran the full check-in schedule)."""
    tracked = _load_tracked()
    finished = [
        t for t in tracked.values()
        if t.get("status") in ("dead", "done") and not t.get("legacy")
        and t.get("alert_price") and t.get("last_pct_change") is not None
    ]
    if not finished:
        return None
    mults = [max((t.get("peak_price") or t["alert_price"]) / t["alert_price"], 1.0) for t in finished]
    n = len(finished)
    hit2 = sum(1 for m in mults if m >= 2)
    up = sum(1 for t in finished if t["last_pct_change"] > 0)
    return (
        f"Track record ({n} finished): {hit2 / n:.0%} hit 2x+ at some point, "
        f"{up / n:.0%} ended above the alert price, avg ATH {sum(mults) / n:.1f}x "
        f"(ATH = highest price seen at our scans)."
    )
