#!/usr/bin/env python3
"""
Re-download the offline manual library described by data/manuals/index.json.

Why the library exists
----------------------
`data/ifu_seed.json` pointed every device at fcc.report. fcc.report now returns
**403 to every automated request**, and the fccid.io mirror IP-blocks after a
handful of fetches — so the "no API key needed" curated path was silently dead.
The manuals are therefore committed to the repo under

    services/gudid-core/data/manuals/

and the IFU pipeline reads them from disk. The demo does not depend on any
third-party site being up, un-rate-limited, or un-blocked.

You should not normally need to run this. It exists so the library is
reproducible and its provenance is auditable: every PDF records where it came
from in index.json, and this script re-fetches from exactly those URLs.

Usage
-----
    python scripts/fetch_manuals.py --list      # show what's on disk
    python scripts/fetch_manuals.py --verify    # checksum + page-count check
    python scripts/fetch_manuals.py            # download anything missing
    python scripts/fetch_manuals.py --force    # re-download everything
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
MANUAL_DIR = REPO / "services" / "gudid-core" / "data" / "manuals"
INDEX = MANUAL_DIR / "index.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 120
DELAY = 1.0

# Hosts known to block automated requests. Their PDFs are committed; if one goes
# missing you have to fetch it in a browser, which is not blocked.
BLOCKED_HOSTS = ("fcc.report", "fccid.io", "apps.fcc.gov")


def load_index() -> dict:
    return json.loads(INDEX.read_text())


def cmd_list(index: dict) -> int:
    print(f"{'':2} {'file':58} {'pages':>6} {'size':>9}  source")
    for m in index["manuals"]:
        path = MANUAL_DIR / m["file"]
        mark = "ok" if path.is_file() else "--"
        size = f"{path.stat().st_size / 1e6:.1f} MB" if path.is_file() else "-"
        print(f"{mark:2} {m['file'][:58]:58} {m.get('pages', '?'):>6} {size:>9}  {m.get('source', '')}")
    present = sum(1 for m in index["manuals"] if (MANUAL_DIR / m["file"]).is_file())
    print(f"\n{present}/{len(index['manuals'])} present in {MANUAL_DIR}")
    return 0


def cmd_verify(index: dict) -> int:
    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber not installed; install it to verify page counts")
        return 1

    bad = 0
    for m in index["manuals"]:
        path = MANUAL_DIR / m["file"]
        if not path.is_file():
            print(f"MISSING  {m['file']}")
            bad += 1
            continue
        head = path.read_bytes()[:4]
        if head != b"%PDF":
            print(f"NOT PDF  {m['file']} (starts with {head!r})")
            bad += 1
            continue
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
        expected = m.get("pages")
        flag = "" if expected in (None, pages) else f"  (index says {expected})"
        print(f"ok       {m['file'][:56]:58} {pages:4d} pages{flag}")
    print(f"\n{len(index['manuals']) - bad} ok, {bad} problem(s)")
    return 0 if bad == 0 else 1


def cmd_fetch(index: dict, force: bool) -> int:
    session = requests.Session()
    ok = skipped = failed = 0

    for m in index["manuals"]:
        path = MANUAL_DIR / m["file"]
        url = m.get("source_url")

        if path.is_file() and not force:
            print(f"[ok] have {m['file']}")
            skipped += 1
            continue
        if not url:
            print(f"[--] {m['file']}: no source_url in index")
            failed += 1
            continue
        if any(h in url for h in BLOCKED_HOSTS):
            print(f"[!!] {m['file']}: source host blocks automated requests")
            print(f"     fetch manually in a browser: {url}")
            failed += 1
            continue

        print(f"[..] {m['file']}")
        try:
            resp = session.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            print(f"     network error: {exc}")
            failed += 1
            continue

        if not resp.ok:
            print(f"     HTTP {resp.status_code}")
            failed += 1
        elif not resp.content.startswith(b"%PDF"):
            print(f"     not a PDF ({len(resp.content)}B, {resp.headers.get('content-type')})")
            failed += 1
        else:
            path.write_bytes(resp.content)
            print(f"     saved {len(resp.content) // 1024} KB")
            ok += 1
        time.sleep(DELAY)

    print(f"\ndownloaded {ok}, already had {skipped}, failed {failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="show library status")
    ap.add_argument("--verify", action="store_true", help="check each PDF opens and page count matches")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    args = ap.parse_args()

    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    index = load_index()

    if args.list:
        return cmd_list(index)
    if args.verify:
        return cmd_verify(index)
    return cmd_fetch(index, args.force)


if __name__ == "__main__":
    sys.exit(main())
