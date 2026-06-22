"""
IFU (Instructions for Use) document URL finder.

Tries in priority order:
  1. AccessGUDID v3 lookup — device record sometimes includes labeling URLs
  2. AccessGUDID v2 device endpoint — richer labeling metadata
  3. Google Custom Search JSON API (requires GOOGLE_API_KEY + GOOGLE_CSE_ID env vars)
  4. Returns a constructed search hint URL the user can open manually

Google Custom Search setup:
  - GOOGLE_API_KEY: from console.cloud.google.com → APIs & Services → Credentials
  - GOOGLE_CSE_ID:  from cse.google.com → your engine's "Search engine ID"
                    (make sure "Search the entire web" is ON in CSE settings)
  Free tier: 100 queries/day. After that: $5 per 1,000 queries.
  For this pipeline (one run per device model, ever) you will not exceed the free tier.

Result shape:
  {
    "url": str | None,          # direct PDF URL if found
    "source": str,              # "gudid_v3" | "gudid_v2" | "google_cse" | "hint_only"
    "search_query": str,        # always set — human-readable search for manual fallback
    "search_hint_url": str,     # always set — Google search URL
  }
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote_plus

import requests

GUDID_V3_BASE = "https://accessgudid.nlm.nih.gov/api/v3"
GUDID_V2_BASE = "https://accessgudid.nlm.nih.gov/api/2.0"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID")
TIMEOUT = 10


def _build_search_query(manufacturer: str, brand: str, model: str) -> str:
    parts = [p for p in [manufacturer, brand, model] if p]
    return " ".join(parts) + " physician manual IFU filetype:pdf"


def _build_hint_url(query: str) -> str:
    return "https://www.google.com/search?q=" + quote_plus(query)


def _extract_labeling_url_from_gudid(device_node: dict) -> Optional[str]:
    """Pull the first PDF URL out of a GUDID device node (v3 or v2 shape)."""
    # v3 shape: device.labelings.labeling (list)
    labelings = device_node.get("labelings") or {}
    labeling_list = labelings.get("labeling") or []
    if isinstance(labeling_list, dict):
        labeling_list = [labeling_list]
    for lab in labeling_list:
        url = lab.get("labelUrl") or lab.get("url") or lab.get("documentUrl")
        if url and url.startswith("http"):
            return url
    return None


def _try_gudid_v3(di: str) -> Optional[str]:
    try:
        resp = requests.get(
            f"{GUDID_V3_BASE}/devices/lookup.json",
            params={"di": di},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        device = (data.get("gudid") or {}).get("device") or {}
        return _extract_labeling_url_from_gudid(device)
    except Exception:
        return None


def _try_gudid_v2(di: str) -> Optional[str]:
    """AccessGUDID v2 has richer labeling data in some records."""
    try:
        resp = requests.get(
            f"{GUDID_V2_BASE}/devices/{di}.json",
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        device = (data.get("gudid") or {}).get("device") or {}
        return _extract_labeling_url_from_gudid(device)
    except Exception:
        return None


def _try_google_cse(query: str) -> Optional[str]:
    """
    Google Custom Search JSON API — returns first PDF result URL.
    Requires GOOGLE_API_KEY and GOOGLE_CSE_ID in environment.
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_CSE_ID,
                "q": query,
                "num": 5,
                "fileType": "pdf",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"[ifu_finder] Google CSE error {resp.status_code}: {resp.text[:200]}")
            return None
        for item in resp.json().get("items") or []:
            link = item.get("link", "")
            if link.lower().endswith(".pdf"):
                return link
        return None
    except Exception as exc:
        print(f"[ifu_finder] Google CSE exception: {exc}")
        return None


def find_ifu(
    manufacturer: str,
    brand: str,
    model: str,
    di: Optional[str] = None,
) -> dict:
    """
    Find the IFU PDF URL for a device.

    Args:
        manufacturer: e.g. "Medtronic"
        brand:        e.g. "Azure XT"
        model:        e.g. "DR MRI SureScan W1DR01"
        di:           Device Identifier (optional but improves GUDID lookup)

    Returns:
        Result dict — always succeeds (url may be None).
    """
    search_query = _build_search_query(manufacturer, brand, model)
    hint_url = _build_hint_url(search_query)

    url: Optional[str] = None
    source = "hint_only"

    if di:
        url = _try_gudid_v3(di)
        if url:
            source = "gudid_v3"
        if not url:
            url = _try_gudid_v2(di)
            if url:
                source = "gudid_v2"

    if not url:
        url = _try_google_cse(search_query)
        if url:
            source = "google_cse"

    return {
        "url": url,
        "source": source,
        "search_query": search_query,
        "search_hint_url": hint_url,
    }
