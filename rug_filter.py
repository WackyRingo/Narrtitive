"""
Optional Solana rug/bundle/insider/sniper check via the Solana Tracker
Data API (data.solanatracker.io). Free tier: 2,500 requests/month, no
card, and only called once per NEW alert (not every candidate checked).

Solana only — that's where this provider's coverage is. Ethereum, BSC and Base
get their own check in evm_security.py.

Needs SOLANA_TRACKER_API_KEY in .env. Leave it blank and this returns
None everywhere — everything else keeps working exactly as before.

Response shape (confirmed against Solana Tracker's docs): risk.score (1-10),
risk.rugged, and risk.risks — a flat array of {name, description, level} factors
such as "Freeze Authority Enabled", "Mint Authority Enabled", "LP Burned" and
"Top 10 Holders". The factors drive the Flags shown on alerts. A nested
risk.snipers/bundlers/insiders.totalPercentage shape is also read when present.

The "rugged" field needs care: if the API returns it as the STRING "false", a
bare `if value:` check treats that non-empty string as truthy, which would flag
every token as rugged. _is_rugged() handles a real bool or a "true"/"false"
string, and the raw value + its type get logged so a wrong assumption is
visible immediately instead of silently flagging everything.
"""

from __future__ import annotations

import requests

import config

BASE_URL = "https://data.solanatracker.io"

# Friendlier wording for the factor names the docs spell out. "LP Burned" appears in the
# risk list when liquidity is NOT fully burned (the docs' own example reads it that way).
_SHORT_FLAGS = {
    "Freeze Authority Enabled": "Freeze auth ON",
    "Mint Authority Enabled": "Mint auth ON",
    "LP Burned": "LP not burned",
}
MAX_FLAGS_SHOWN = 4


def _is_rugged(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _flag_names(risks) -> list:
    """Danger-level factors first, then warn-level ones, in friendlier wording."""
    danger, warn = [], []
    for factor in risks or []:
        name = factor.get("name") or ""
        if not name:
            continue
        short = _SHORT_FLAGS.get(name, name)
        level = str(factor.get("level") or "").lower()
        if level == "danger":
            danger.append(short)
        elif level in ("warn", "warning"):
            warn.append(short)
    return danger + [w for w in warn if w not in danger]


def get_rug_check(chain: str, address: str) -> dict | None:
    """
    Returns a dict with score (1-10, higher = riskier), rugged (bool), flag names,
    and sniper/bundler/insider percentages where available — or None if
    unavailable (wrong chain, no key, or the request failed for any reason).
    """
    if chain != "solana":
        return None

    if not config.SOLANA_TRACKER_API_KEY:
        print("[rug_filter] skipped — SOLANA_TRACKER_API_KEY not set")
        return None

    print(f"[rug_filter] requesting risk data for {address}")
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
        print(f"[rug_filter] request failed: {resp.status_code} — body: {resp.text[:300]}")
        return None

    try:
        data = resp.json() or {}
    except Exception as e:
        print(f"[rug_filter] response wasn't valid JSON: {e} — raw: {resp.text[:300]}")
        return None

    risk = data.get("risk") or {}
    if not risk:
        print(f"[rug_filter] got a 200 but no 'risk' field — top-level keys: {list(data.keys())}")
        return None

    score = risk.get("score")
    rugged_raw = risk.get("rugged")
    rugged = _is_rugged(rugged_raw)
    flags = _flag_names(risk.get("risks"))

    factor_mentions = {}
    for factor in risk.get("risks") or []:
        lname = (factor.get("name") or "").lower()
        for key in ("sniper", "bundler", "insider"):
            if key in lname and key not in factor_mentions:
                factor_mentions[key] = factor.get("name")

    sniper_pct = (risk.get("snipers") or {}).get("totalPercentage")
    bundler_pct = (risk.get("bundlers") or {}).get("totalPercentage")
    insider_pct = (risk.get("insiders") or {}).get("totalPercentage")

    print(
        f"[rug_filter] got risk data — score={score!r}, rugged_raw={rugged_raw!r} "
        f"({type(rugged_raw).__name__}) -> parsed as {rugged}, flags={flags}, "
        f"raw risk keys: {list(risk.keys())}"
    )

    return {
        "score": score,
        "rugged": rugged,
        "danger_flags": flags,
        "factor_mentions": factor_mentions,
        "sniper_pct": sniper_pct,
        "bundler_pct": bundler_pct,
        "insider_pct": insider_pct,
    }


def format_rug_line(rug: dict | None) -> str | None:
    """One line for the alert's security row, or None if there's nothing to show."""
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
    if rug.get("danger_flags"):
        parts.append("Flags: " + ", ".join(rug["danger_flags"][:MAX_FLAGS_SHOWN]))
    elif rug.get("factor_mentions"):
        parts.append("Noted: " + ", ".join(rug["factor_mentions"].values()))

    return " · ".join(parts) if parts else None
