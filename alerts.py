"""
Formats and fires an alert when the chain scanner flags a token —
Phanes-style stats block plus a "Read" section underneath, generated
by the free rule-based logic in chain_scanner.py. Console output
always happens; Telegram is used too if configured in .env. No paid
API of any kind anywhere in this file.
"""

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


def _fmt_usd(n) -> str:
    return f"${n:,.0f}" if n is not None else "—"


def _fmt_pct(n) -> str:
    if n is None:
        return "—"
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.0f}%"


def format_alert(token: dict) -> str:
    lines = [
        "",
        "🔔 UNUSUAL ACTIVITY",
        f"${token['symbol']} — {token['name']}",
        f"{token['chain']}" + (f" | {token['age_hours']:.1f}h old" if token.get("age_hours") is not None else ""),
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


def send_alert(token: dict):
    message = format_alert(token)
    print(message)

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": message},
                timeout=10,
            )
        except Exception as e:
            print(f"[alerts] Telegram send failed: {e}")
