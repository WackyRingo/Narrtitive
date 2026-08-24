"""
Formats and fires alerts — both new "unusual activity" alerts and the
later checkpoint check-ins that report what actually happened. Console
output always happens; Telegram is used too if configured in .env.

Telegram sends check the actual response and retry once on a rate
limit, and pace themselves slightly — sending a big batch back-to-back
with no delay can get silently rate-limited by Telegram, which
requests.post() alone won't tell you about.
"""

import time

import requests

import config

EXPLORER_BASE = {
    "bsc": "https://bscscan.com/token/",
    "ethereum": "https://etherscan.io/token/",
    "base": "https://basescan.org/token/",
    "solana": "https://solscan.io/token/",
    "arbitrum": "https://arbiscan.io/token/",
    "polygon": "https://polygonscan.com/token/",
}

TELEGRAM_SEND_DELAY_SECONDS = 1.1  # stay under Telegram's per-chat rate limit


def _fmt_usd(n) -> str:
    return f"${n:,.0f}" if n is not None else "—"


def _fmt_pct(n) -> str:
    if n is None:
        return "—"
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.0f}%"


def format_alert(token: dict) -> str:
    score = token.get("activity_score")
    score_line = f" | Activity: {score}/100 ({token.get('activity_label')})" if score is not None else ""

    lines = [
        "",
        "🔔 UNUSUAL ACTIVITY",
        f"${token['symbol']} — {token['name']}",
        f"{token['chain']}" + (f" | {token['age_hours']:.1f}h old" if token.get("age_hours") is not None else "") + score_line,
        "",
        "Stats",
        f"├ Price     {token.get('price_usd') or '—'}  ({_fmt_pct(token.get('price_change_1h'))} 1h, {_fmt_pct(token.get('price_change_24h'))} 24h)",
        f"├ MCap      {_fmt_usd(token.get('market_cap'))}",
        f"├ Volume    {_fmt_usd(token.get('volume_24h'))} (24h)",
        f"├ Liquidity {_fmt_usd(token.get('liquidity_usd'))}",
        f"└ Txns 1h   B {token.get('buys_1h') if token.get('buys_1h') is not None else '—'}"
        f"  S {token.get('sells_1h') if token.get('sells_1h') is not None else '—'}",
        "",
        "Read",
        f"└ {token.get('quick_read', '')}",
        "",
    ]

    if token.get("url"):
        lines.append(token["url"])
    explorer = EXPLORER_BASE.get(token.get("chain"))
    if explorer and token.get("address"):
        lines.append(f"{explorer}{token['address']}")

    return "\n".join(lines)


def format_checkpoint_alert(item: dict) -> str:
    pct_str = _fmt_pct(item.get("pct_change"))
    lines = [
        "",
        f"📍 {item['hours']:.0f}H CHECK-IN",
        f"${item.get('symbol')} — {item.get('name')}",
        f"Since alert: {pct_str}",
    ]
    if item.get("market_cap"):
        lines.append(f"MCap now: {_fmt_usd(item['market_cap'])}")
    if item.get("url"):
        lines.append(item["url"])
    return "\n".join(lines)


def _send_telegram(message: str) -> bool:
    """Actually checks whether Telegram accepted the message, and retries once on a rate limit."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": message}

    for attempt in range(2):
        try:
            resp = requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"[alerts] Telegram send failed (network error): {e}")
            return False

        if resp.status_code == 200:
            return True

        if resp.status_code == 429 and attempt == 0:
            retry_after = 2
            try:
                retry_after = (resp.json().get("parameters") or {}).get("retry_after", 2)
            except Exception:
                pass
            print(f"[alerts] Telegram rate-limited, waiting {retry_after}s and retrying once")
            time.sleep(retry_after)
            continue

        print(f"[alerts] Telegram send failed: {resp.status_code} {resp.text[:200]}")
        return False

    return False


def _send(message: str, telegram_eligible: bool = True):
    print(message)
    if telegram_eligible and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        _send_telegram(message)
        time.sleep(TELEGRAM_SEND_DELAY_SECONDS)


def send_alert(item: dict):
    if item.get("type") == "checkpoint":
        _send(format_checkpoint_alert(item))  # check-ins always go through — they're rare and valuable
        return

    score = item.get("activity_score")
    eligible = score is None or score >= config.MIN_TELEGRAM_SCORE
    _send(format_alert(item), telegram_eligible=eligible)
