"""
Free primary detector: watches DexScreener's public "latest token
profiles" and "latest boosted tokens" feeds for brand-new tokens, then
checks each new one's actual trading data for activity that looks
unusual for its age. No Twitter, no API key, no cost — just DexScreener's
free, keyless endpoints.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import config

BASE_URL = "https://api.dexscreener.com"
SEEN_CACHE_PATH = Path("seen_tokens.json")


def _load_seen() -> dict:
    if SEEN_CACHE_PATH.exists():
        return json.loads(SEEN_CACHE_PATH.read_text())
    return {}


def _save_seen(seen: dict):
    # Cap the file so it doesn't grow forever — keep the most recently touched entries.
    if len(seen) > 5000:
        newest = sorted(seen.items(), key=lambda kv: kv[1].get("seen_at", 0), reverse=True)
        seen = dict(newest[:5000])
    SEEN_CACHE_PATH.write_text(json.dumps(seen))


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


def get_pair_data(chain_id: str, token_address: str) -> dict | None:
    """Pull live price/liquidity/volume data for a known token address."""
    resp = requests.get(f"{BASE_URL}/latest/dex/tokens/{token_address}", timeout=10)
    if resp.status_code != 200:
        return None
    pairs = resp.json().get("pairs") or []
    chain_pairs = [p for p in pairs if p.get("chainId") == chain_id] or pairs
    if not chain_pairs:
        return None
    # If a token has several pools, use the one with the most liquidity.
    return max(chain_pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0)


def _is_unusually_active(pair: dict) -> bool:
    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    volume_24h = (pair.get("volume") or {}).get("h24") or 0
    buys_1h = (pair.get("txns") or {}).get("h1", {}).get("buys") or 0

    if liquidity < config.MIN_LIQUIDITY_USD:
        return False  # too thin to be a meaningful signal either way

    if liquidity > 0 and (volume_24h / liquidity) >= config.VOLUME_TO_LIQUIDITY_RATIO:
        return True
    if buys_1h >= config.MIN_BUYS_PER_HOUR:
        return True
    return False


def generate_quick_read(token: dict) -> str:
    """
    Free, rule-based read on the numbers — no API call, no cost. Mirrors
    the kind of context a person would give looking at these stats by
    hand. See ai_read.py for an optional Claude-powered upgrade to this.
    """
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
        skew = buys / (buys + sells)
        if skew >= 0.7:
            notes.append(f"Buyers well ahead of sellers in the last hour ({buys} buys vs {sells} sells).")
        elif skew <= 0.35:
            notes.append(f"Sellers outnumbering buyers in the last hour ({sells} sells vs {buys} buys) — activity, not necessarily bullish activity.")

    if token.get("age_hours") is not None and token["age_hours"] < 2:
        notes.append(f"Only {token['age_hours']:.1f}h old — very early, which cuts both ways.")

    notes.append(
        "No holder or rug-check data yet (that's the rug-filter module, still to build) — "
        "treat this as a lead to check manually, not a signal to act on."
    )
    return " ".join(notes)


def scan_for_active_new_tokens() -> list[dict]:
    """
    Check DexScreener's newest-token feeds for anything both new (not seen
    on a previous cycle) and already trading more actively than its age
    would suggest.
    """
    seen = _load_seen()
    hits = []

    candidates = get_latest_profiles() + get_latest_boosts()
    for c in candidates:
        address = c.get("tokenAddress")
        chain_id = c.get("chainId")
        if not address or address in seen:
            continue
        seen[address] = {"seen_at": time.time()}

        pair = get_pair_data(chain_id, address)
        if not pair or not _is_unusually_active(pair):
            continue

        base = pair.get("baseToken", {})
        created_ms = pair.get("pairCreatedAt")
        age_hours = None
        if created_ms:
            created = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600

        token = {
            "name": base.get("name"),
            "symbol": base.get("symbol"),
            "chain": chain_id,
            "address": address,
            "pair_address": pair.get("pairAddress"),
            "price_usd": pair.get("priceUsd"),
            "price_change_1h": (pair.get("priceChange") or {}).get("h1"),
            "price_change_24h": (pair.get("priceChange") or {}).get("h24"),
            "market_cap": pair.get("marketCap"),
            "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
            "volume_24h": (pair.get("volume") or {}).get("h24"),
            "buys_1h": (pair.get("txns") or {}).get("h1", {}).get("buys"),
            "sells_1h": (pair.get("txns") or {}).get("h1", {}).get("sells"),
            "age_hours": age_hours,
            "url": pair.get("url"),
        }
        token["quick_read"] = generate_quick_read(token)
        hits.append(token)

    _save_seen(seen)
    return hits
