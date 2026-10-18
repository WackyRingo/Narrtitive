"""
Copycat waves: when a theme goes viral, the feed fills with near-identical coins
("Quantum Inu", "Quantum Pad", "Quantum Jean"...). Within one batch of new alerts,
this groups coins that share a theme word, so the oldest coin of the wave gets a
normal alert and the rest collapse into a single digest message.

The theme match is word-based on purpose: a coin matches a theme if one of its
name/symbol words equals, starts with, or ends with it ("stonk" matches Stonklynx
and BabyStonk, but "cat" does NOT match "Duplicate"). Very short or generic words
can't be themes. Grouping only hides the *extra* alerts: every follower is still
tracked, still counts in the leaderboard and /stats, and still gets an image card
if it runs 2x+.
"""

from __future__ import annotations

import re

import config

SHORT_THEMES = {"cat", "dog", "ape"}  # 3-letter words that are real themes
STOP_WORDS = {
    "coin", "token", "the", "official", "meme", "memes", "memecoin", "pump", "fun", "solana",
    "sol", "and", "for", "with", "new", "just", "real", "this", "that", "from", "your",
}


def _words(item: dict) -> set:
    text = f"{item.get('name') or ''} {item.get('symbol') or ''}".lower()
    return set(re.findall(r"[^\W\d_]{3,}", text))


def _matches(words: set, theme: str) -> bool:
    return any(w == theme or w.startswith(theme) or w.endswith(theme) for w in words)


def _candidates(wordsets: list) -> set:
    found = set()
    for words in wordsets:
        for w in words:
            if w in STOP_WORDS:
                continue
            if len(w) >= 4 or w in SHORT_THEMES:
                found.add(w)
            if len(w) >= 7:
                found.add(w[:5])  # "stonklynx" and "stonkitty" share the theme "stonk"
    return found - STOP_WORDS


def plan(items: list) -> list:
    """Returns groups in original order: {"leader": item, "followers": [items], "theme": str|None}.
    A coin with no wave is a group of one with no followers."""
    solo = [{"leader": i, "followers": [], "theme": None} for i in items]
    if not config.WAVE_COLLAPSE or len(items) < config.WAVE_MIN:
        return solo

    wordsets = [_words(i) for i in items]
    candidates = _candidates(wordsets)
    unassigned = set(range(len(items)))
    waves = []  # (theme, [indexes])

    while True:
        best = None
        for theme in candidates:
            members = [k for k in unassigned if _matches(wordsets[k], theme)]
            if len(members) >= config.WAVE_MIN and (
                best is None or (len(members), len(theme)) > (len(best[1]), len(best[0]))
            ):
                best = (theme, members)
        if best is None:
            break
        waves.append(best)
        unassigned -= set(best[1])
        candidates.discard(best[0])

    in_wave = {}
    for theme, members in waves:
        ranked = sorted(
            members,
            key=lambda k: (-(items[k].get("age_hours") or 0), -(items[k].get("activity_score") or 0)),
        )  # oldest first: the original, not the copycats
        followers = sorted((items[k] for k in ranked[1:]), key=lambda i: -(i.get("activity_score") or 0))
        in_wave[ranked[0]] = {"leader": items[ranked[0]], "followers": followers, "theme": theme}
        for k in ranked[1:]:
            in_wave[k] = None  # swallowed by a leader

    groups = []
    for k, item in enumerate(items):
        if k in in_wave:
            if in_wave[k] is not None:
                groups.append(in_wave[k])
        else:
            groups.append({"leader": item, "followers": [], "theme": None})
    return groups
