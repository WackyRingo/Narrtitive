"""
Runs a single scan cycle and exits — the entry point for GitHub Actions
(or any other scheduler that starts a fresh run rather than keeping a
process alive). For running continuously on your own machine instead,
use main.py.
"""

from chain_scanner import scan_for_active_new_tokens, track_record_summary
from alerts import send_alert


def main():
    results = scan_for_active_new_tokens()
    new_alerts = [r for r in results if r.get("type") != "checkpoint"]
    checkins = [r for r in results if r.get("type") == "checkpoint"]
    print(f"Scan complete: {len(new_alerts)} new alert(s), {len(checkins)} check-in(s).")

    for item in results:
        send_alert(item)

    summary = track_record_summary()
    if summary:
        print(summary)


if __name__ == "__main__":
    main()
