"""
Entry point for running continuously on your own machine. Polls on a
loop instead of running once and exiting — for GitHub Actions, use
scan_once.py instead.

Run with: python main.py
Stop with Ctrl+C.
"""

import time

import config
from scan_once import run_cycle


def main():
    print(f"Scanning DexScreener every {config.POLL_INTERVAL_SECONDS}s (free, no API keys). Ctrl+C to stop.")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[main] error this cycle: {e}")
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
