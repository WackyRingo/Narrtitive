"""
Runs a single scan cycle and exits — the entry point for GitHub Actions
(or any other scheduler that starts a fresh run rather than keeping a
process alive). For running continuously on your own machine instead,
use main.py, which just calls run_cycle() on a timer.

One cycle: scan DexScreener, deliver the resulting Telegram messages (new
alerts, edits to existing ones, digests, cards), save the message ids that
delivery produced, then do the leaderboard housekeeping.

Every stage is wrapped so an unexpected error prints and gets skipped
rather than crashing the whole run — the point is that a bad cycle
should degrade, not take the workflow down with it.
"""

import importlib

# Every file the bot can't run without. If one is missing from the repo (a partial upload),
# say exactly which, instead of leaving a bare traceback.
_REQUIRED = ["config", "rug_filter", "chain_scanner", "tg", "waves", "evm_security", "alerts"]


def _preflight():
    problems = []
    for name in _REQUIRED:
        try:
            importlib.import_module(name)
        except Exception as e:
            problems.append(f"{name}.py ({e})")
    if problems:
        print("[scan_once] CAN'T START — these files are missing or broken in the repo: " + "; ".join(problems))
        print("[scan_once] Upload every file from the latest set (see the README), then run again.")
        raise SystemExit(1)


_preflight()

from chain_scanner import apply_updates, scan_for_active_new_tokens, track_record_summary
from alerts import deliver

try:
    from leaderboard import run_housekeeping
except Exception as e:  # without leaderboard.py / analysis.py the bot still runs, just without them
    print(f"[scan_once] leaderboard unavailable ({e}) — /lb, /stats and the pinned board are off")
    run_housekeeping = None


def run_cycle():
    try:
        results = scan_for_active_new_tokens()
    except Exception as e:
        print(f"[scan_once] unexpected error during scan: {e}")
        results = []

    new_alerts = [r for r in results if r.get("type") == "alert"]
    checkins = [r for r in results if r.get("type") == "checkpoint"]
    dead = [r for r in results if r.get("type") == "dead"]
    print(f"Scan complete: {len(new_alerts)} new alert(s), {len(checkins)} check-in(s), {len(dead)} died.")

    updates = {}
    try:
        deliver(results, updates)
    except Exception as e:
        print(f"[scan_once] error delivering messages: {e}")
    finally:
        try:
            apply_updates(updates)  # remember message ids / tracking lines, even after a partial failure
        except Exception as e:
            print(f"[scan_once] couldn't save message ids: {e}")

    if run_housekeeping:
        try:
            run_housekeeping()  # leaderboard history, /lb and /stats commands, pinned board
        except Exception as e:
            print(f"[scan_once] leaderboard step failed: {e}")

    try:
        summary = track_record_summary()
        if summary:
            print(summary)
    except Exception as e:
        print(f"[scan_once] error computing track record: {e}")


def main():
    run_cycle()


if __name__ == "__main__":
    main()
