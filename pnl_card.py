"""
Draws a PNL-style card (a PNG) for a coin that has run, so its check-in
arrives as a shareable image instead of plain text. Inspired by the look of
call-tracker PNL cards, drawn from scratch — no logos or artwork from anywhere.

Everything on the card comes from what the scanner already tracks: the market
cap at alert time, the highest price seen since (the ATH), and how long after
the alert that peak was seen. The ATH is the highest price seen at our scans,
so a spike that rose and fell between two scans can make the real peak higher.

Needs Pillow (in requirements.txt). If Pillow or a font is missing, render()
raises and the caller falls back to a plain text message — nothing breaks.
"""

from __future__ import annotations

import io
from pathlib import Path

W, H = 1200, 630

_BOLD_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
]
_REGULAR_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "DejaVuSans.ttf",
]


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    for path in (_BOLD_FONTS if bold else _REGULAR_FONTS):
        try:
            if path.startswith("/") and not Path(path).exists():
                continue
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)  # Pillow 10.1+
    except TypeError:
        return ImageFont.load_default()


def _fmt_cap(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.2f}M"
    if v >= 1e3:
        return f"${v / 1e3:.1f}K"
    return f"${v:.0f}"


def _fmt_mult(m: float) -> str:
    return f"{m:.0f}x" if m >= 10 else f"{m:.1f}x"


def _clean(text, fallback: str) -> str:
    """The card font covers Latin/Greek/Cyrillic, not CJK or emoji — drop what it can't draw."""
    kept = "".join(ch for ch in str(text or "") if ord(ch) < 0x2000 and ch.isprintable()).strip()
    return kept or fallback


def _fit(draw, text: str, max_width: int, start: int, bold: bool):
    size = start
    while size > 14:
        font = _font(size, bold)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 4
    return _font(14, bold)


def _accent(mult: float):
    if mult >= 10:
        return (251, 191, 36)   # gold
    if mult >= 3:
        return (34, 211, 238)   # cyan
    return (34, 197, 94)        # green


def render(item: dict) -> bytes:
    """PNG bytes for a check-in/dead item that carries peak_mult and alert_mcap."""
    from PIL import Image, ImageDraw, ImageFilter

    mult = float(item["peak_mult"])
    entry_cap = float(item["alert_mcap"])
    ath_cap = entry_cap * mult
    accent = _accent(mult)

    symbol = "$" + _clean(item.get("symbol"), "TOKEN")
    name = _clean(item.get("name"), "")[:34]

    # background: vertical gradient plus a soft glow behind the multiplier
    mask = Image.linear_gradient("L").resize((W, H))
    bg = Image.composite(Image.new("RGB", (W, H), (21, 28, 58)), Image.new("RGB", (W, H), (8, 11, 26)), mask)
    canvas = bg.convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W // 2 - 380, 120, W // 2 + 380, 480), fill=accent + (85,))
    canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(95)))
    draw = ImageDraw.Draw(canvas)

    # header: symbol + name, brand tag on the right
    draw.text((64, 40), symbol, font=_fit(draw, symbol, 720, 78, True), fill=(255, 255, 255))
    if name:
        draw.text((66, 138), name, font=_font(30), fill=(154, 164, 199))
    tag = "NARRATIVE TRACKER"
    tag_font = _font(24, True)
    tag_w = draw.textbbox((0, 0), tag, font=tag_font)[2]
    draw.text((W - 64 - tag_w, 56), tag, font=tag_font, fill=(110, 120, 160))

    # the multiplier, with a blurred copy underneath as a glow
    mult_text = _fmt_mult(mult)
    mult_font = _fit(draw, mult_text, 980, 300, True)
    box = draw.textbbox((0, 0), mult_text, font=mult_font)
    mx, my = (W - (box[2] - box[0])) // 2 - box[0], 190 - box[1]
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(halo).text((mx, my), mult_text, font=mult_font, fill=accent + (255,))
    canvas = Image.alpha_composite(canvas, halo.filter(ImageFilter.GaussianBlur(22)))
    draw = ImageDraw.Draw(canvas)
    draw.text((mx, my), mult_text, font=mult_font, fill=accent)

    # called-at -> ATH line
    line = f"Called at {_fmt_cap(entry_cap)}   \u2192   ATH {_fmt_cap(ath_cap)}"
    line_font = _fit(draw, line, 1060, 44, False)
    lb = draw.textbbox((0, 0), line, font=line_font)
    draw.text(((W - (lb[2] - lb[0])) // 2 - lb[0], 468), line, font=line_font, fill=(235, 238, 250))

    # stat pills
    pills = []
    if item.get("peak_hours") is not None:
        pills.append(f"ATH {item['peak_hours']:.1f}h after alert")
    if item.get("alert_score") is not None:
        pills.append(f"Activity {item['alert_score']}/100")
    if item.get("alert_risk") is not None:
        pills.append(f"Risk {item['alert_risk']}/10")
    if pills:
        pill_font, pad, gap, height = _font(26), 22, 16, 52
        widths = [draw.textbbox((0, 0), p, font=pill_font)[2] + 2 * pad for p in pills]
        x = (W - (sum(widths) + gap * (len(pills) - 1))) // 2
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for p, w in zip(pills, widths):
            ld.rounded_rectangle((x, 534, x + w, 534 + height), radius=26, fill=(255, 255, 255, 26), outline=accent + (120,), width=2)
            ld.text((x + pad, 534 + 9), p, font=pill_font, fill=(225, 230, 248))
            x += w + gap
        canvas = Image.alpha_composite(canvas, layer)
        draw = ImageDraw.Draw(canvas)

    foot = "ATH = highest price seen at scan times \u00b7 not financial advice"
    fb = draw.textbbox((0, 0), foot, font=_font(17))
    draw.text(((W - (fb[2] - fb[0])) // 2, 600), foot, font=_font(17), fill=(95, 105, 145))

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
