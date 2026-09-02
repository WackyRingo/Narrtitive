"""
Runs a single scan cycle and exits — the entry point for GitHub Actions
(or any other scheduler that starts a fresh run rather than keeping a
process alive). For running continuously on your own machine instead,
use main.py.

Every stage is wrapped so an unexpected error prints and gets skipped
rather than crashing the whole run — the point is that a bad cycle
should degrade, not take the workflow down with it.
"""

from chain_scanner import scan_for_active_new_tokens, track_record_summary
from alerts import send_alert


def main():
    try:
        results = scan_for_active_new_tokens()
    except Exception as e:
        print(f"[scan_once] unexpected error during scan: {e}")
        results = []

    new_alerts = [r for r in results if r.get("type") != "checkpoint"]
    checkins = [r for r in results if r.get("type") == "checkpoint"]
    print(f"Scan complete: {len(new_alerts)} new alert(s), {len(checkins)} check-in(s).")

    for item in results:
        try:
            send_alert(item)
        except Exception as e:
            print(f"[scan_once] error sending an alert: {e}")

    try:
        summary = track_record_summary()
        if summary:
            print(summary)
    except Exception as e:
        print(f"[scan_once] error computing track record: {e}")


if __name__ == "__main__":
    main()
