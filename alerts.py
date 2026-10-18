"""
Formats and delivers everything the bot says in Telegram.

The goal is a quiet chat. Each coin gets ONE message — a compact alert — and as
the coin is checked later (1h/6h/24h/72h, or when it dies) that same message is
edited in place with a tracking line, instead of sending a new message each time.
Only genuinely big events get a fresh message: a new alert, an image card when a
coin has run 2x+, and a short note when a high-scoring call dies.

Other noise-reducers: follow-ups are sent silently (no phone buzz), copycat waves
collapse into one digest (see waves.py), and links are tappable words.

If an edit can't be made (message deleted, coin alerted before this layout, edit
refused), the follow-up falls back to a normal standalone message so nothing is lost.
Everything is also printed to the console / Actions log, in plain text.
"""

from __future__ import annotations

import html
import re

import config
import tg
import waves
from evm_security import format_evm_line
from rug_filter import format_rug_line

EXPLORER = {
    "bsc": ("BscScan", "https://bscscan.com/token/"),
    "ethereum": ("Etherscan", "https://etherscan.io/token/"),
    "base": ("BaseScan", "https://basescan.org/token/"),
    "solana": ("Solscan", "https://solscan.io/token/"),
    "arbitrum": ("Arbiscan", "https://arbiscan.io/token/"),
    "polygon": ("Polygonscan", "https://polygonscan.com/token/"),
}

# Bubblemaps uses its own short chain codes, not the same ones DexScreener returns.
BUBBLEMAPS_CHAIN = {
    "solana": "sol",
    "ethereum": "eth",
    "bsc": "bsc",
    "base": "base",
    "arbitrum": "arbi",
    "polygon": "poly",
    "robinhood": "robinhood",
}
EVM_CHAINS = ("ethereum", "bsc", "base")


# ---------- small formatting helpers ----------

def _fmt_usd(n) -> str:
    return f"${n:,.0f}" if n is not None else "—"


def _fmt_pct(n) -> str:
    if n is None:
        return "—"
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.0f}%"


def _fmt_mult(m) -> str:
    if m is None:
        return "—"
    return f"{m:.0f}x" if m >= 10 else f"{m:.1f}x"


def _ath_text(item: dict) -> str:
    mult = item.get("peak_mult")
    text = f"ATH {_fmt_mult(mult)}"
    if mult and mult >= 1.05 and item.get("peak_hours") is not None:
        text += f" ({item['peak_hours']:.1f}h after alert)"
    return text


def _late_note(item: dict) -> str:
    """Scans can run late, so a "6H" check-in may really be sent at 7.7h — say so when it's off."""
    elapsed, due = item.get("elapsed_hours"), item.get("hours")
    if elapsed is not None and due is not None and elapsed - due >= 0.25:
        return f" ({elapsed:.1f}h in)"
    return ""


def _origin_line(item: dict):
    origin = []
    if item.get("alert_score") is not None:
        origin.append(f"Activity {item['alert_score']}/100")
    if item.get("alert_risk") is not None:
        origin.append(f"Risk {item['alert_risk']}/10")
    return "Alerted at: " + " · ".join(origin) if origin else None


def bubblemaps_url(chain: str, address: str):
    bm_chain = BUBBLEMAPS_CHAIN.get(chain)
    return f"https://app.bubblemaps.io/{bm_chain}/token/{address}" if bm_chain else None


def _link(label_html: str, url: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{label_html}</a>'


def _console(html_text: str):
    """The Actions log gets the same message as plain text."""
    print(html.unescape(re.sub(r"<[^>]+>", "", html_text)))


# ---------- the compact alert ----------

def _heads_up(item: dict):
    """A short warning line — only when something is actually unusual, not boilerplate."""
    notes = []
    vol, liq = item.get("volume_24h") or 0, item.get("liquidity_usd") or 0
    if liq > 0 and vol / liq >= 25:
        notes.append("extreme turnover for the pool size")
    buys, sells = item.get("buys_1h") or 0, item.get("sells_1h") or 0
    if buys + sells > 0 and buys / (buys + sells) < 0.5:
        notes.append("sellers ahead of buyers")
    age = item.get("age_hours")
    if age is not None and age >= 12:
        notes.append(f"not new ({age:.0f}h old)")
    g24 = item.get("price_change_24h")
    if g24 is not None and g24 <= -50:
        notes.append(f"already {g24:.0f}% on 24h")
    elif g24 is not None and g24 >= 1000:
        notes.append(f"already {g24:+.0f}% today")
    return "⚠️ " + " · ".join(notes[:3]) if notes else None


def _security_line(item: dict):
    chain = item.get("chain")
    if item.get("rug_check") is not None:
        text = format_rug_line(item["rug_check"])
    elif item.get("evm_check") is not None:
        text = format_evm_line(item["evm_check"])
    elif chain == "solana":
        text = "Rug check unavailable this time"
    elif chain in EVM_CHAINS:
        text = "Security check unavailable this time"
    else:
        return None
    return f"🛡 {tg.esc(text)}" if text else None


def format_alert_html(item: dict) -> str:
    esc = tg.esc
    score = item.get("activity_score")
    meta = [esc(item.get("chain"))]
    if item.get("age_hours") is not None:
        meta.append(f"{item['age_hours']:.1f}h old")
    if score is not None:
        meta.append(f"Activity {score}/100 ({esc(item.get('activity_label'))})")

    stats = [f"MCap {_fmt_usd(item.get('market_cap'))}", f"Liq {_fmt_usd(item.get('liquidity_usd'))}"]
    vol, liq = item.get("volume_24h") or 0, item.get("liquidity_usd") or 0
    if liq > 0:
        stats.append(f"Vol {vol / liq:.0f}x")
    buys, sells = item.get("buys_1h"), item.get("sells_1h")
    if buys is not None and sells is not None and buys + sells > 0:
        stats.append(f"Buys {buys / (buys + sells):.0%}")

    lines = [
        f"🔔 <b>${esc(item.get('symbol'))}</b> — {esc(item.get('name'))}",
        " · ".join(meta),
        " · ".join(stats),
        f"{_fmt_pct(item.get('price_change_1h'))} 1h · {_fmt_pct(item.get('price_change_24h'))} 24h",
    ]
    security = _security_line(item)
    if security:
        lines.append(security)
    heads_up = _heads_up(item)
    if heads_up:
        lines.append(esc(heads_up))

    links = []
    if item.get("url"):
        links.append(_link("DexScreener", item["url"]))
    explorer = EXPLORER.get(item.get("chain"))
    if explorer and item.get("address"):
        links.append(_link(explorer[0], explorer[1] + item["address"]))
    bm = bubblemaps_url(item.get("chain"), item["address"]) if item.get("address") else None
    if bm:
        links.append(_link("Bubblemaps", bm))
    if links:
        lines.append(" · ".join(links))
    return "\n".join(lines)


def format_digest_html(leader: dict, followers: list, theme) -> str:
    esc = tg.esc
    head = f"🌊 <b>+{len(followers)} similar to ${esc(leader.get('symbol'))}</b>"
    if theme:
        head += f" ({esc(theme)} wave)"
    lines = [head]
    for f in followers[:8]:
        label = f"${esc(f.get('symbol'))}"
        label = _link(label, f["url"]) if f.get("url") else label
        bits = [_fmt_usd(f.get("market_cap")), f"Act {f.get('activity_score')}"]
        risk = (f.get("rug_check") or {}).get("score")
        if risk is not None:
            bits.append(f"Risk {risk}")
        lines.append(f"• {label} — " + " · ".join(bits))
    if len(followers) > 8:
        lines.append(f"…and {len(followers) - 8} more")
    return "\n".join(lines)


# ---------- follow-ups ----------

def format_followup_html(item: dict) -> str:
    """A standalone check-in / death message — used as the fallback when a message can't be edited."""
    esc = tg.esc
    sym, name = esc(item.get("symbol")), esc(item.get("name"))
    now = _fmt_pct(item.get("pct_change"))
    if item.get("type") == "dead":
        lines = [f"💀 <b>DEAD</b> · ${sym} — {name}", f"Now {now} · {_ath_text(item)}"]
        stats = []
        if item.get("market_cap") is not None:
            stats.append(f"MCap {_fmt_usd(item['market_cap'])}")
        if item.get("liquidity_usd") is not None:
            stats.append(f"Liq {_fmt_usd(item['liquidity_usd'])}")
        if stats:
            lines.append(" · ".join(stats))
        lifetime = item.get("lifetime_hours")
        lasted = f"Lasted {lifetime:.1f}h — " if lifetime is not None else ""
        lines.append(f"{lasted}{esc(item.get('reason') or 'collapsed')}. No more check-ins.")
    else:
        lines = [
            f"📍 <b>{item['hours']:.0f}H CHECK-IN</b>{_late_note(item)} · ${sym} — {name}",
            f"Now {now} · {_ath_text(item)}"
            + (f" · MCap {_fmt_usd(item['market_cap'])}" if item.get("market_cap") else ""),
        ]
    origin = _origin_line(item)
    if origin:
        lines.append(origin)
    if item.get("url"):
        lines.append(_link("DexScreener", item["url"]))
    return "\n".join(lines)


def render_track(track: list, item: dict, dead=None) -> str:
    """The tracking block appended to a coin's original alert."""
    parts = [f"{e['h']:.0f}H {_fmt_pct(e.get('pct'))}" for e in track if e.get("h") is not None]
    if dead and dead.get("pct") is not None:
        parts.append(f"last {_fmt_pct(dead['pct'])}")
    line = ("📍 " + " · ".join(parts)) if parts else "📍 tracking"
    lines = [f"{line}  |  {_ath_text(item)}"]
    if dead:
        after = dead.get("after")
        when = f" after {after:.1f}h" if after is not None else ""
        lines.append(f"💀 Dead{when} — {tg.esc(dead.get('reason') or 'collapsed')}. No more check-ins.")
    return "\n".join(lines)


def _try_card(item: dict, caption: str) -> bool:
    try:
        import pnl_card
        png = pnl_card.render(item)
    except Exception as e:
        print(f"[alerts] PNL card failed, sending text only: {e}")
        return False
    return bool(tg.send_photo(png, caption, silent=not config.CARD_NOTIFY))


# ---------- delivery ----------

def _alert_eligible(item: dict) -> bool:
    score = item.get("activity_score")
    return score is None or score >= config.MIN_TELEGRAM_SCORE


def _deliver_alert(item: dict, updates: dict, wave=None):
    text = format_alert_html(item)
    _console(text)
    addr = item.get("address")
    upd = {"wave": wave} if wave else {}
    if tg.ready():
        msg_id = tg.send_text(text, silent=False)
        if msg_id:
            upd.update({"msg_id": msg_id, "msg_html": text})
    if addr and upd:
        updates.setdefault(addr, {}).update(upd)


def _deliver_digest(group: dict, updates: dict):
    text = format_digest_html(group["leader"], group["followers"], group["theme"])
    _console(text)
    if tg.ready():
        tg.send_text(text, silent=False)
    for follower in group["followers"]:
        if follower.get("address"):
            updates.setdefault(follower["address"], {}).update({"quiet": True, "wave": "follow"})


def _deliver_followup(item: dict, updates: dict):
    kind = item.get("type")
    addr = item.get("address")
    standalone = format_followup_html(item)
    _console(standalone)

    score = item.get("alert_score")
    if not (tg.ready() and (score is None or score >= config.MIN_TELEGRAM_SCORE)):
        return  # weak alerts were never pushed to Telegram, so their follow-ups aren't either

    card_sent = _try_card(item, standalone) if item.get("send_card") else False
    if item.get("quiet"):
        return  # a copycat from a wave: only an image card breaks its silence

    track = list(item.get("track") or [])
    dead = None
    if kind == "checkpoint":
        track.append({"h": item.get("hours"), "pct": item.get("pct_change")})
    else:
        dead = {"after": item.get("lifetime_hours"), "reason": item.get("reason"), "pct": item.get("pct_change")}
    if addr:
        upd = {"track": track}
        if dead:
            upd["dead"] = dead
        updates.setdefault(addr, {}).update(upd)

    edited = False
    if config.EDIT_IN_PLACE and item.get("msg_id") and item.get("msg_html"):
        edited = tg.edit_text(item["msg_id"], item["msg_html"] + "\n\n" + render_track(track, item, dead))
    if not edited and not card_sent:
        tg.send_text(standalone, silent=config.QUIET_FOLLOWUPS)

    if kind == "dead" and edited and (score or 0) >= config.LOUD_DEATH_SCORE:
        pct = _fmt_pct(item.get("pct_change"))
        tg.send_text(
            f"💀 <b>${tg.esc(item.get('symbol'))}</b> (Activity {score}) died after "
            f"{item.get('lifetime_hours') or 0:.1f}h · {pct} · {_ath_text(item)}",
            silent=True,
        )


def deliver(results: list, updates=None) -> dict:
    """Sends everything one scan produced. Returns {address: fields} to persist on the tracked coins
    (message ids, tracking lines, wave roles). `updates` is filled as it goes, so a crash partway
    through still leaves the progress made so far."""
    updates = {} if updates is None else updates
    new_alerts = [r for r in results if r.get("type") == "alert"]
    followups = [r for r in results if r.get("type") in ("checkpoint", "dead")]

    for item in new_alerts:
        if not _alert_eligible(item):
            _console(format_alert_html(item))  # weak: log only
    eligible = [r for r in new_alerts if _alert_eligible(r)]

    for group in waves.plan(eligible):
        try:
            followers = group["followers"]
            _deliver_alert(group["leader"], updates, wave="lead" if followers else None)
            if followers:
                _deliver_digest(group, updates)
        except Exception as e:
            print(f"[alerts] error delivering an alert: {e}")

    for item in followups:
        try:
            _deliver_followup(item, updates)
        except Exception as e:
            print(f"[alerts] error delivering a follow-up: {e}")
    return updates


def send_alert(item: dict) -> dict:
    """Single-item convenience wrapper, kept for older callers."""
    return deliver([item])
