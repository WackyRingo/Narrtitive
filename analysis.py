"""
/stats — what actually predicted results.

For every "settled" call (dead, finished its check-ins, or at least 24h old) it
groups calls by the conditions they were alerted under — Activity score, coin
age, 1h gain, buy ratio, liquidity, chain, rug-check risk, wave role — and shows
for each group: how many calls, what share reached 2x+, what share died, and the
median ATH. It exists so thresholds get tuned from evidence, not guesses.

Groups with fewer than MIN_BUCKET calls are labelled "too few" rather than
shown as a percentage: 2 of 3 calls "hitting 2x" is noise, not a finding.
ATH is the highest price seen at our scans, so every number here is a floor.
"""

from __future__ import annotations

import statistics

MIN_BUCKET = 5
SETTLED_AFTER_HOURS = 24

# (title, record field, buckets); numeric buckets are (label, low, high) with low inclusive, high exclusive
FACTORS = [
    ("Activity score", "alert_score", [("<60", None, 60), ("60–74", 60, 75), ("75+", 75, None)]),
    ("Coin age at alert", "age", [("<1h", None, 1), ("1–6h", 1, 6), ("6h+", 6, None)]),
    ("1h price gain", "gain_1h", [("<50%", None, 50), ("50–200%", 50, 200), ("200%+", 200, None)]),
    ("Buy share (1h)", "buy_ratio", [("<55%", None, 0.55), ("55–70%", 0.55, 0.70), ("70%+", 0.70, None)]),
    ("Liquidity", "liq", [("<$25K", None, 25_000), ("$25–60K", 25_000, 60_000), ("$60K+", 60_000, None)]),
    ("Rug-check risk (Solana)", "alert_risk", [("0–3", None, 4), ("4–6", 4, 7), ("7–10", 7, None)]),
]
CATEGORICAL = [
    ("Chain", "chain", None),
    ("Wave role", "wave", {None: "not in a wave", "lead": "wave leader", "follow": "wave copycat"}),
]


def _in_bucket(value, low, high) -> bool:
    return value is not None and (low is None or value >= low) and (high is None or value < high)


def _summary(label: str, group: list) -> str:
    n = len(group)
    if n < MIN_BUCKET:
        return f"{label:<14} n={n} · too few to judge"
    peaks = [c["peak_mult"] for c in group]
    hit = sum(1 for p in peaks if p >= 2) / n
    dead = sum(1 for c in group if c.get("status") == "dead") / n
    return f"{label:<14} n={n} · {hit:.0%} hit 2x+ · {dead:.0%} dead · median {statistics.median(peaks):.1f}x"


def _settled(calls: dict, now: float) -> list:
    out = []
    for c in calls.values():
        age_h = (now - c.get("alerted_at", now)) / 3600
        if c.get("status") in ("dead", "done") or age_h >= SETTLED_AFTER_HOURS:
            out.append(c)
    return out


def build(calls: dict, now: float):
    settled = _settled(calls, now)
    if len(settled) < MIN_BUCKET:
        return (
            "📐 STATS — not enough settled calls yet.\n"
            f"A call is settled once it has died, finished its check-ins, or is {SETTLED_AFTER_HOURS}h+ old. "
            f"Need at least {MIN_BUCKET}; have {len(settled)}."
        )

    lines = [f"📐 WHAT PREDICTED RESULTS · {len(settled)} settled calls", ""]
    for title, field, buckets in FACTORS:
        rows = []
        for label, low, high in buckets:
            group = [c for c in settled if _in_bucket(c.get(field), low, high)]
            if group:
                rows.append(_summary(label, group))
        if rows:
            lines.append(title)
            lines += [("└ " if i == len(rows) - 1 else "├ ") + r for i, r in enumerate(rows)]
            lines.append("")

    for title, field, names in CATEGORICAL:
        groups = {}
        for c in settled:
            groups.setdefault(c.get(field), []).append(c)
        rows = []
        for key in sorted(groups, key=lambda k: -len(groups[k])):
            label = (names or {}).get(key, key) if names is not None else key
            if label is None:
                continue
            rows.append(_summary(str(label), groups[key]))
        if len(rows) > 1 or (rows and field == "wave"):
            lines.append(title)
            lines += [("└ " if i == len(rows) - 1 else "├ ") + r for i, r in enumerate(rows)]
            lines.append("")

    lines.append(
        f"Groups under {MIN_BUCKET} calls aren't judged. ATH = highest price seen at scans, so these are floors. "
        "Look for big gaps between groups that hold up as the numbers grow — not single results."
    )
    return "\n".join(lines)
