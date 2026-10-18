"""
Free security check for Ethereum, BSC and Base tokens via GoPlus
(api.gopluslabs.io — no key needed, undocumented rate limits, so it's only
called once per NEW alert). Covers what Solana Tracker's check doesn't:
honeypot detection, buy/sell tax, mintable supply, hidden owner, unverified
code, and how much liquidity is locked.

GoPlus returns its flags as the STRINGS "0" and "1" — and the string "0" is
truthy in Python — so every flag goes through _flag(), which compares the text
instead of trusting truthiness. Returns None whenever the check can't be done
(unsupported chain, API down, token unknown) so callers just skip the line.
"""

from __future__ import annotations

import requests

BASE_URL = "https://api.gopluslabs.io/api/v1/token_security"
CHAIN_IDS = {"ethereum": "1", "bsc": "56", "base": "8453"}


def _flag(value):
    """'1' -> True, '0' -> False, missing/blank -> None (unknown)."""
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip() == "1"


def _pct(value):
    """GoPlus fractions like '0.05' -> 5.0 (percent); blank/garbage -> None."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value) * 100
    except (TypeError, ValueError):
        return None


def get_evm_check(chain: str, address: str):
    chain_id = CHAIN_IDS.get(chain)
    if not chain_id or not address:
        return None

    try:
        resp = requests.get(f"{BASE_URL}/{chain_id}", params={"contract_addresses": address}, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"[evm_security] request failed (network error): {e}")
        return None
    if resp.status_code != 200:
        print(f"[evm_security] request failed: {resp.status_code} — body: {resp.text[:200]}")
        return None
    try:
        body = resp.json() or {}
    except ValueError:
        print("[evm_security] response wasn't valid JSON")
        return None

    result = body.get("result") or {}
    entry = result.get(address.lower())
    if entry is None and result:
        entry = next(iter(result.values()))
    if not entry:
        print(f"[evm_security] no data for {address} (code={body.get('code')}, message={body.get('message')})")
        return None

    lp_holders = entry.get("lp_holders") or []
    lp_locked = None
    if lp_holders:
        lp_locked = sum((_pct(h.get("percent")) or 0) for h in lp_holders if str(h.get("is_locked")) == "1")

    try:
        holders = int(entry.get("holder_count"))
    except (TypeError, ValueError):
        holders = None

    check = {
        "honeypot": _flag(entry.get("is_honeypot")),
        "buy_tax": _pct(entry.get("buy_tax")),
        "sell_tax": _pct(entry.get("sell_tax")),
        "mintable": _flag(entry.get("is_mintable")),
        "hidden_owner": _flag(entry.get("hidden_owner")),
        "can_reclaim": _flag(entry.get("can_take_back_ownership")),
        "open_source": _flag(entry.get("is_open_source")),
        "lp_locked_pct": lp_locked,
        "holders": holders,
    }
    print(
        f"[evm_security] {chain} {address}: honeypot={check['honeypot']}, "
        f"tax={check['buy_tax']}/{check['sell_tax']}, mintable={check['mintable']}, "
        f"lp_locked={check['lp_locked_pct']}, raw keys={len(entry)}"
    )
    return check


def _tax(value) -> str:
    return "?" if value is None else f"{value:.0f}%"


def format_evm_line(check):
    """One short line for the alert's security row, or None if there's no check."""
    if check is None:
        return None
    parts = []
    if check.get("honeypot") is True:
        parts.append("🚫 HONEYPOT")
    elif check.get("honeypot") is False:
        parts.append("Not a honeypot")

    buy, sell = check.get("buy_tax"), check.get("sell_tax")
    if buy is not None or sell is not None:
        high = (buy or 0) >= 10 or (sell or 0) >= 10
        parts.append(f"Tax {_tax(buy)}/{_tax(sell)}" + (" ⚠️" if high else ""))

    flags = []
    if check.get("mintable"):
        flags.append("mintable")
    if check.get("hidden_owner"):
        flags.append("hidden owner")
    if check.get("can_reclaim"):
        flags.append("owner can reclaim")
    if check.get("open_source") is False:
        flags.append("unverified code")
    if flags:
        parts.append("⚠️ " + ", ".join(flags))

    if check.get("lp_locked_pct") is not None:
        parts.append(f"LP locked {check['lp_locked_pct']:.0f}%")
    return " · ".join(parts) or "No flags returned"
