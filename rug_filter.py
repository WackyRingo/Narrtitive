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

Parsing note: Solana Tracker's own docs confirm risk.score, risk.rugged,
and risk.risks (a flat array of {name, level} factor objects) as the
real response shape. An earlier version of this file assumed a nested
risk.snipers/bundlers/insiders.totalPercentage shape that turned out
to be wrong — that's kept below as a fallback attempt in case it does
exist on some responses, but risk.risks is the confirmed source, and
the raw keys get logged so a future mismatch is visible immediately
instead of silently returning nothing.
"""

from __future__ import annotations

import requests

import config

BASE_URL = "https://data.solanatracker.io"


def get_rug_check(chain: str, address: str) -> dict | None:
    """
    Returns a dict with score (1-10, higher = riskier), rugged (bool),
    named danger-level risk factors, and sniper/bundler/insider
    percentages where available — or None if unavailable (wrong chain,
    no key, or the request failed for any reason).
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
    rugged = risk.get("rugged")

    # Confirmed shape: risk.risks is a flat array of {name, level} factor objects.
    # Pull out danger-level flags, and separately look for anything mentioning
    # snipers/bundlers/insiders by name so those signals surface even without
    # a dedicated percentage field.
    danger_flags = []
    factor_mentions = {}
    for factor in risk.get("risks") or []:
        name = factor.get("name") or ""
        if factor.get("level") == "danger":
            danger_flags.append(name)
        lname = name.lower()
        for key in ("sniper", "bundler", "insider"):
            if key in lname and key not in factor_mentions:
                factor_mentions[key] = name

    # Fallback attempt at the nested-object shape, in case it exists too.
    sniper_pct = (risk.get("snipers") or {}).get("totalPercentage")
    bundler_pct = (risk.get("bundlers") or {}).get("totalPercentage")
    insider_pct = (risk.get("insiders") or {}).get("totalPercentage")

    print(
        f"[rug_filter] got risk data — score={score}, rugged={rugged}, "
        f"{len(risk.get('risks') or [])} risk factor(s), raw risk keys: {list(risk.keys())}"
    )

    return {
        "score": score,
        "rugged": rugged,
        "danger_flags": danger_flags,
        "factor_mentions": factor_mentions,
        "sniper_pct": sniper_pct,
        "bundler_pct": bundler_pct,
        "insider_pct": insider_pct,
    }


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
    if rug.get("danger_flags"):
        shown = ", ".join(rug["danger_flags"][:3])
        parts.append(f"Flags: {shown}")
    elif rug.get("factor_mentions"):
        shown = ", ".join(rug["factor_mentions"].values())
        parts.append(f"Noted: {shown}")

    return " · ".join(parts) if parts else None
