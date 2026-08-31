"""
Optional Solana rug/bundle/insider/sniper check via the Solana Tracker
Data API (data.solanatracker.io). Free tier: 2,500 requests/month, no
card, no rate limit issue at this project's realistic volume since
it's only called once per NEW alert (not every candidate checked).

Solana only — that's where this provider's coverage is. Other chains
get a bubble map link instead (see alerts.py) but no numeric rug data
yet; a second provider would be needed for BSC/ETH/Base.

Needs SOLANA_TRACKER_API_KEY in .env. Leave it blank and this returns
None everywhere — everything else keeps working exactly as before.
"""

from __future__ import annotations

import requests

import config

BASE_URL = "https://data.solanatracker.io"


def get_rug_check(chain: str, address: str) -> dict | None:
    """
    Returns a dict with score (1-10, higher = riskier), rugged (bool),
    and sniper/bundler/insider percentages, or None if unavailable —
    wrong chain, no API key set, or the request failed for any reason.
    """
    if chain != "solana" or not config.SOLANA_TRACKER_API_KEY:
        return None

    try:
        resp = requests.get(
            f"{BASE_URL}/tokens/{address}",
            headers={"x-api-key": config.SOLANA_TRACKER_API_KEY},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        print(f"[rug_filter] request failed (network error): {e}")
        return None

    if resp.status_code != 200:
        print(f"[rug_filter] request failed: {resp.status_code}")
        return None

    try:
        risk = (resp.json() or {}).get("risk") or {}
        return {
            "score": risk.get("score"),
            "rugged": risk.get("rugged"),
            "sniper_pct": (risk.get("snipers") or {}).get("totalPercentage"),
            "bundler_pct": (risk.get("bundlers") or {}).get("totalPercentage"),
            "insider_pct": (risk.get("insiders") or {}).get("totalPercentage"),
        }
    except Exception as e:
        print(f"[rug_filter] unexpected response shape: {e}")
        return None


def format_rug_line(rug: dict | None) -> str | None:
    """One line for the alert's Security section, or None if there's nothing to show."""
    if rug is None:
        return None
    if rug.get("rugged"):
        return "⚠️ Flagged as already rugged by Solana Tracker."

    parts = []
    if rug.get("score") is not None:
        parts.append(f"Risk {rug['score']}/10")
    if rug.get("sniper_pct"):
        parts.append(f"Snipers {rug['sniper_pct']:.0f}%")
    if rug.get("bundler_pct"):
        parts.append(f"Bundlers {rug['bundler_pct']:.0f}%")
    if rug.get("insider_pct"):
        parts.append(f"Insiders {rug['insider_pct']:.0f}%")
    return " · ".join(parts) if parts else None
