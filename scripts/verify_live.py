#!/usr/bin/env python3
"""scripts/verify_live.py — live-site verification (v2, Nov 26, 2026)
DRAFT ONLY — not seeded. Paste path in repo: scripts/verify_live.py
Identical file in both repos.

Replaces the v1/v2 inline `python3 -c` one-liners in nightly.yml, whose
backslash quoting broke under YAML/shell. All logic lives here instead.

Reads the expected value from the local data file just committed:
  - dict JSON (oil prices.json): the --field value at top level
  - list JSON (rates supplier_offers.json): the max --field across entries
Then polls the live data URL until the live body contains that value,
20 tries x 30s = a 10-minute window, and exits 0. Exits 1 if the value
never lands. A bare HTTP 200 is never treated as verification.
"""
import argparse, json, sys, time
from pathlib import Path

import requests

def expected_value(data_path: str, field: str) -> str:
    data = json.loads(Path(data_path).read_text())
    if isinstance(data, dict):
        return str(data[field])
    if isinstance(data, list):
        return str(max(str(e[field]) for e in data if field in e))
    raise ValueError("data file is neither a JSON object nor a list")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--live-url", required=True)
    ap.add_argument("--field", default="checked_date")
    ap.add_argument("--tries", type=int, default=20)
    ap.add_argument("--delay", type=int, default=30)
    a = ap.parse_args()
    expect = expected_value(a.data, a.field)
    print(f"Expecting live {a.field}: {expect} at {a.live_url}")
    for i in range(1, a.tries + 1):
        try:
            body = requests.get(a.live_url, timeout=30).text
            if expect in body:
                print(f"Live verified on try {i}.")
                return 0
        except Exception as e:
            print(f"try {i}: fetch failed ({e})")
        if i < a.tries:
            time.sleep(a.delay)
    print("Live verification failed: expected value never appeared.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
