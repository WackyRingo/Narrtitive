"""
Runs a single scan cycle and exits — the entry point for GitHub Actions
(or any other scheduler that starts a fresh run rather than keeping a
process alive). For running continuously on your own machine instead,
use main.py.
"""

from chain_scanner import scan_for_active_new_tokens
from alerts import send_alert


def main():
    hits = scan_for_active_new_tokens()
    print(f"Scan complete: {len(hits)} match(es).")
    for token in hits:
        send_alert(token)


if __name__ == "__main__":
    main()
