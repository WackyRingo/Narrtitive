"""
Entry point for running continuously on your own machine. Polls on a
loop instead of running once and exiting — for GitHub Actions, use
scan_once.py instead.

Run with: python main.py
Stop with Ctrl+C.
"""

import time

import config
from chain_scanner import scan_for_active_new_tokens, track_record_summary
from alerts import send_alert


def main():
    print(f"Scanning DexScreener every {config.POLL_INTERVAL_SECONDS}s (free, no API keys). Ctrl+C to stop.")
    while True:
        try:
            results = scan_for_active_new_tokens()
            for item in results:
                send_alert(item)
            summary = track_record_summary()
            if summary:
                print(summary)
        except Exception as e:
            print(f"[main] error this cycle: {e}")
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
