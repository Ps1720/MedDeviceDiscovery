"""
IFU (Instructions for Use) document URL finder.

Tries in priority order:
  1. AccessGUDID v3  — labeling URLs embedded in the FDA record
  2. AccessGUDID v2  — richer labeling metadata
  3. Manufacturer site — Bing search restricted to the manufacturer's own manual domain
  4. FCC database     — Bing search on fcc.report (contains RF-device manuals submitted to FCC)
  5. Bing general     — full-web Bing search for PDF
  6. Google CSE       — fallback if Bing key not set
  7. DuckDuckGo       — last-resort web search, no key required
  8. hint_only        — returns a Google search URL for manual lookup

Manufacturer manual domains (used for targeted Bing site: searches):
  Medtronic          → manuals.medtronic.com
  Abbott / St. Jude  → cardiovascular.abbott
  Boston Scientific  → bostonscientific.com
  Biotronik          → biotronik.com
  LivaNova           → livanova.com
  Nevro              → nevro.com
  Neuropace          → neuropace.com
  Tandem             → tandemdiabetes.com
  Insulet / Omnipod  → insulet.com
  Dexcom             → dexcom.com
  Abbott Diabetes    → diabetes.abbott

Result shape:
  {
    "url": str | None,
    "source": str,   # "gudid_v3"|"gudid_v2"|"manufacturer_site"|"fcc"|"bing"|"google_cse"|"duckduckgo"|"hint_only"
    "search_query": str,
    "search_hint_url": str,
  }
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote_plus

import requests

try:
    from duckduckgo_search import DDGS
    _DDG_AVAILABLE = True
except ImportError:
    _DDG_AVAILABLE = False

GUDID_V3_BASE = "https://accessgudid.nlm.nih.gov/api/v3"
GUDID_V2_BASE = "https://accessgudid.nlm.nih.gov/api/2.0"
BING_API_KEY   = os.environ.get("BING_API_KEY")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")   # kept as fallback
GOOGLE_CSE_ID  = os.environ.get("GOOGLE_CSE_ID")
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


def _try_duckduckgo(query: str) -> Optional[str]:
    """DuckDuckGo text search — no API key required, used as fallback."""
    if not _DDG_AVAILABLE:
        return None
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=10)
            for r in results or []:
                link = r.get("href", "")
                if link.lower().endswith(".pdf"):
                    return link
        return None
    except Exception as exc:
        print(f"[ifu_finder] DuckDuckGo search failed: {exc}")
        return None


# Manufacturer name fragments → their official manual domain
_MANUFACTURER_DOMAINS: dict[str, str] = {
    "medtronic":        "manuals.medtronic.com",
    "abbott":           "cardiovascular.abbott",
    "st. jude":         "cardiovascular.abbott",
    "stjude":           "cardiovascular.abbott",
    "boston scientific":"bostonscientific.com",
    "boston":           "bostonscientific.com",
    "biotronik":        "biotronik.com",
    "livanova":         "livanova.com",
    "cyberonics":       "livanova.com",
    "nevro":            "nevro.com",
    "neuropace":        "neuropace.com",
    "tandem":           "tandemdiabetes.com",
    "insulet":          "insulet.com",
    "omnipod":          "insulet.com",
    "dexcom":           "dexcom.com",
}


def _bing_query(query: str, label: str) -> Optional[str]:
    """Run a single Bing Web Search query and return the first PDF URL found."""
    if not BING_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": BING_API_KEY},
            params={"q": query, "count": 10, "mkt": "en-US", "responseFilter": "Webpages"},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"[ifu_finder] Bing {label} error {resp.status_code}: {resp.text[:200]}")
            return None
        for item in (resp.json().get("webPages") or {}).get("value") or []:
            url = item.get("url", "")
            if url.lower().endswith(".pdf"):
                return url
        return None
    except Exception as exc:
        print(f"[ifu_finder] Bing {label} exception: {exc}")
        return None


def _try_manufacturer_site(manufacturer: str, brand: str, model: str) -> Optional[str]:
    """
    Bing search restricted to the manufacturer's own manual domain.
    Most likely source of the correct physician manual.
    """
    mfr_lower = manufacturer.lower()
    domain = None
    for key, d in _MANUFACTURER_DOMAINS.items():
        if key in mfr_lower:
            domain = d
            break
    if not domain:
        return None
    # Search within the manufacturer site for brand + model manual PDF
    parts = [p for p in [brand, model] if p]
    query = f'site:{domain} {" ".join(parts)} physician manual filetype:pdf'
    result = _bing_query(query, "manufacturer_site")
    if not result:
        # Fallback: looser query without filetype restriction (some sites serve PDFs without .pdf extension)
        query2 = f'site:{domain} {" ".join(parts)} manual'
        result = _bing_query(query2, "manufacturer_site_loose")
    return result


def _try_fcc(manufacturer: str, brand: str, model: str) -> Optional[str]:
    """
    Search the FCC ID database (fcc.report) via Bing.
    fcc.report hosts device manuals and test reports submitted for RF certification —
    a reliable source for implantable devices with wireless/RF components (pacemakers,
    ICDs, CGMs, insulin pumps). The filing typically contains the full physician manual.
    """
    parts = [p for p in [manufacturer, brand, model] if p]
    query = f'site:fcc.report {" ".join(parts)} filetype:pdf'
    return _bing_query(query, "fcc")


def _try_bing(query: str) -> Optional[str]:
    """Bing general web search — full web, any domain."""
    return _bing_query(query, "general")


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
        url = _try_manufacturer_site(manufacturer, brand, model)
        if url:
            source = "manufacturer_site"

    if not url:
        url = _try_fcc(manufacturer, brand, model)
        if url:
            source = "fcc"

    if not url:
        url = _try_bing(search_query)
        if url:
            source = "bing"

    if not url:
        url = _try_google_cse(search_query)
        if url:
            source = "google_cse"

    if not url:
        url = _try_duckduckgo(search_query)
        if url:
            source = "duckduckgo"

    return {
        "url": url,
        "source": source,
        "search_query": search_query,
        "search_hint_url": hint_url,
    }
