"""
Thin Telegram helper used by everything that talks to the chat: send a message,
edit one in place, pin one, send a photo. Messages use HTML formatting (so links
can be tappable words instead of long raw URLs), can be sent silently (no phone
buzz), and a rate limit gets one patient retry.

All text passed in must already be HTML-safe — build it with esc() for anything
that comes from outside (token names, symbols).
"""

from __future__ import annotations

import html
import time

import requests

import config

SEND_DELAY_SECONDS = 1.1  # stay under Telegram's per-chat rate limit


def ready() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def esc(text) -> str:
    """Make arbitrary text safe to drop into an HTML message."""
    return html.escape("" if text is None else str(text), quote=False)


def _form(data: dict) -> dict:
    # multipart forms carry strings, and Telegram wants lowercase true/false
    return {k: ("true" if v is True else "false" if v is False else v) for k, v in data.items()}


def _call(method: str, data: dict, files=None):
    """Returns Telegram's JSON reply, {"ok": False, ...} on a refusal, or None on a network failure."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    for attempt in range(2):
        try:
            if files:
                resp = requests.post(url, data=_form(data), files=files, timeout=45)
            else:
                resp = requests.post(url, json=data, timeout=30)
        except Exception as e:
            print(f"[tg] {method} failed (network error): {e}")
            return None
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 200 and body.get("ok"):
            return body
        if resp.status_code == 429 and attempt == 0:
            wait = (body.get("parameters") or {}).get("retry_after", 2)
            print(f"[tg] rate-limited, waiting {wait}s and retrying once")
            time.sleep(min(wait, 30))
            continue
        return {"ok": False, "status": resp.status_code, "description": body.get("description") or resp.text[:200]}
    return None


def send_text(html_text: str, silent: bool = False):
    """Sends a message; returns its message_id, or None if it didn't go through."""
    if not ready():
        return None
    body = _call("sendMessage", {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": bool(silent),
    })
    time.sleep(SEND_DELAY_SECONDS)
    if body and body.get("ok"):
        return (body.get("result") or {}).get("message_id")
    print(f"[tg] sendMessage failed: {body}")
    return None


def send_photo(png: bytes, caption_html: str, silent: bool = False):
    """Sends an image with a caption; returns its message_id, or None."""
    if not ready():
        return None
    body = _call("sendPhoto", {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "caption": caption_html[:1000],
        "parse_mode": "HTML",
        "disable_notification": bool(silent),
    }, files={"photo": ("pnl.png", png, "image/png")})
    time.sleep(SEND_DELAY_SECONDS)
    if body and body.get("ok"):
        return (body.get("result") or {}).get("message_id")
    print(f"[tg] sendPhoto failed: {body}")
    return None


def edit_text(message_id, html_text: str) -> bool:
    """Replaces a message's text in place. 'Not modified' counts as success."""
    if not ready() or not message_id:
        return False
    body = _call("editMessageText", {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    time.sleep(SEND_DELAY_SECONDS)
    if body and body.get("ok"):
        return True
    if body and "not modified" in str(body.get("description", "")).lower():
        return True
    print(f"[tg] editMessageText failed: {body}")
    return False


def pin(message_id) -> bool:
    """Pins a message quietly. Works in a private chat; in a group the bot must be an admin."""
    if not ready() or not message_id:
        return False
    body = _call("pinChatMessage", {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "disable_notification": True,
    })
    if body and body.get("ok"):
        return True
    print(f"[tg] pinChatMessage failed: {body}")
    return False
