"""
IFU (Instructions for Use) document URL finder.

Tries in priority order:
  0. Curated seed table  — hand-verified FCC User Manual PDFs for ~15 common periop
                           devices (no network call needed; instant lookup)
  1. AccessGUDID v3      — labeling URLs embedded in the FDA record
  2. AccessGUDID v2      — richer labeling metadata
  3. EUDAMED             — EU device database; returns IFU URL when present (mandate
                           phasing in through May 2026 — groundwork for future coverage)
  4. Manufacturer site   — Bing search restricted to the manufacturer's own manual domain
  5. FCC database        — two-step: find filing page via Bing, then scrape to pick the
                           document specifically labeled "User Manual" (not test reports)
  6. Bing general        — full-web Bing search for PDF
  7. Google CSE          — fallback if Bing key not set
  8. DuckDuckGo          — last-resort web search, no key required
  9. hint_only           — returns a Google search URL for manual lookup

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
    "source": str,   # "gudid_v3"|"gudid_v2"|"eudamed"|"manufacturer_site"|"fcc"
                     # |"bing"|"google_cse"|"duckduckgo"|"hint_only"
    "search_query": str,
    "search_hint_url": str,
  }
"""

from __future__ import annotations

import json
import os
from pathlib import Path
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

# Curated seed table — loaded once, cached in memory
_SEED_PATH = Path(__file__).parent / "data" / "ifu_seed.json"
_seed_cache: list[dict] | None = None

# Offline manual library — PDFs committed to the repo (data/manuals/).
# This is tried FIRST: no network, no rate limits, no bot-blocking. The
# fcc.report URLs in ifu_seed.json now 403 on every automated request, so the
# local library is what actually makes the curated path work.
_MANUAL_DIR = Path(__file__).parent / "data" / "manuals"
_MANUAL_INDEX = _MANUAL_DIR / "index.json"
_manual_cache: list[dict] | None = None


def _load_manuals() -> list[dict]:
    global _manual_cache
    if _manual_cache is None:
        try:
            entries = json.loads(_MANUAL_INDEX.read_text())["manuals"]
            # Only advertise manuals whose PDF is actually present.
            _manual_cache = [e for e in entries if (_MANUAL_DIR / e["file"]).is_file()]
            missing = len(entries) - len(_manual_cache)
            if missing:
                print(f"[ifu_finder] {missing} indexed manual(s) missing from disk "
                      f"— run scripts/fetch_manuals.py")
        except Exception as exc:  # noqa: BLE001
            print(f"[ifu_finder] manual index load error: {exc}")
            _manual_cache = []
    return _manual_cache


def _matches(entry: dict, mfr_l: str, brand_l: str, model_l: str) -> bool:
    """
    Shared matcher: any manufacturer pattern + any brand pattern in brand/model.

    Manufacturer accepts a list because GUDID records carry the name registered
    at the time of listing, which is often a company since acquired — Abbott's
    cardiac rhythm devices are still filed under "ST. JUDE MEDICAL, INC.". An
    entry may use `manufacturer_patterns` (list) or `manufacturer_pattern` (str).
    """
    patterns = entry.get("manufacturer_patterns") or [
        entry.get("manufacturer_pattern", "")
    ]
    if not any(p and p in mfr_l for p in patterns):
        return False
    return any(
        bp in brand_l or bp in model_l
        for bp in entry.get("brand_patterns", [])
    )


def find_local_manual(manufacturer: str, brand: str, model: str = "") -> Optional[dict]:
    """
    Best offline manual for this device, or None.

    Returns the index entry with an added "path" (absolute) and "url"
    (app-relative, served by the /manuals/<file> route). Preference goes to the
    entry with the most brand-pattern specificity, so a device-specific manual
    wins over a family-wide one.
    """
    mfr_l = (manufacturer or "").lower()
    brand_l = (brand or "").lower()
    model_l = (model or "").lower()

    hits = [e for e in _load_manuals() if _matches(e, mfr_l, brand_l, model_l)]
    if not hits:
        return None

    def rank(entry: dict) -> tuple[int, int]:
        # `priority` (1 = primary clinician manual, 3 = supplement/checklist) is
        # what decides. Without it a 2-page checklist can beat the 300-page
        # physician's manual just by matching a longer brand string.
        matched = [
            bp for bp in entry.get("brand_patterns", [])
            if bp in brand_l or bp in model_l
        ]
        return (entry.get("priority", 2), -max(len(bp) for bp in matched))

    best = min(hits, key=rank)
    return {
        **best,
        "path": str(_MANUAL_DIR / best["file"]),
        "url": f"/manuals/{best['file']}",
    }


def list_local_manuals() -> list[dict]:
    """Every manual present on disk (for the admin/tools page)."""
    return [
        {**e, "url": f"/manuals/{e['file']}"}
        for e in _load_manuals()
    ]


def _try_local(manufacturer: str, brand: str, model: str) -> Optional[str]:
    """
    Step -1: the offline library. Returns the app-relative "/manuals/<file>"
    form — the one canonical way a local manual is referenced. It is what gets
    stored in the DB, shown in the UI, and opened in a browser;
    ifu_extractor resolves it back to a path on disk.
    """
    hit = find_local_manual(manufacturer, brand, model)
    if not hit:
        return None
    print(f"[ifu_finder] local manual hit: {hit['file']}")
    return hit["url"]


def _load_seed() -> list[dict]:
    global _seed_cache
    if _seed_cache is None:
        try:
            _seed_cache = json.loads(_SEED_PATH.read_text())["devices"]
        except Exception as exc:
            print(f"[ifu_finder] seed load error: {exc}")
            _seed_cache = []
    return _seed_cache


def _try_curated(manufacturer: str, brand: str, model: str) -> Optional[tuple[str, str]]:
    """
    Look up the device in the curated seed table (data/ifu_seed.json).

    Returns (ifu_url, fcc_id) if matched, None otherwise.
    Matching is case-insensitive substring: manufacturer_pattern must appear in
    manufacturer, and at least one brand_pattern must appear in brand or model.

    No network calls — instant lookup from a hand-verified local table.
    """
    mfr_l   = manufacturer.lower()
    brand_l  = (brand  or "").lower()
    model_l  = (model  or "").lower()

    for entry in _load_seed():
        # Skip entries with no confirmed URL (filing page only)
        url = entry.get("ifu_url", "")
        if not url or "/FCC-ID/" not in url or not url.endswith(".pdf"):
            # Entry only has a filing page URL — delegate to FCC scraper later
            continue

        if entry.get("manufacturer_pattern", "") not in mfr_l:
            continue

        matched = any(
            bp in brand_l or bp in model_l
            for bp in entry.get("brand_patterns", [])
        )
        if matched:
            return url, entry.get("fcc_id", "")

    return None


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
    Two-step FCC database lookup via fcc.report.

    Step 1 — find the FCC filing page (Bing site:fcc.report/FCC-ID search).
    Step 2 — scrape that page and pick the document labeled 'User Manual'
             or 'Users Manual', not just the first PDF (avoids test reports,
             SAR reports, and cover letters).

    fcc.report hosts manuals submitted for RF certification — pacemakers, ICDs,
    CGMs, and insulin pumps all require FCC certification and submit full manuals.
    """
    import re as _re

    parts = [p for p in [manufacturer, brand, model] if p]

    # Step 1: find the FCC filing index page
    filing_url = _bing_query(
        f'site:fcc.report/FCC-ID {" ".join(parts)}', "fcc_page"
    )
    if not filing_url:
        # Fallback: find any PDF on fcc.report and return it
        return _bing_query(
            f'site:fcc.report {" ".join(parts)} filetype:pdf', "fcc_pdf"
        )

    # Normalise to the filing index URL (strip any document path after the FCC ID)
    m = _re.match(r'(https://fcc\.report/FCC-ID/[^/\?]+)', filing_url)
    filing_base = m.group(1) if m else filing_url

    # Step 2: scrape the filing page — pick the User Manual document
    result = _scrape_fcc_filing(filing_base)
    return result or filing_url


def _scrape_fcc_filing(filing_base_url: str) -> Optional[str]:
    """
    Given a fcc.report filing page URL, scrape and return the User Manual PDF URL.
    Shared by _try_fcc() and any direct FCC ID lookup.
    """
    import re as _re
    try:
        resp = requests.get(
            filing_base_url,
            timeout=TIMEOUT,
            headers={"User-Agent": "PeriopUDI/1.0"},
        )
        if resp.status_code != 200:
            return None
        rows = _re.findall(
            r'<td[^>]*><a href="/FCC-ID/[^"]+">([^<]+)</a></td>.*?'
            r'<td><a href="(/FCC-ID/[^"]+\.pdf)"',
            resp.text, _re.DOTALL,
        )
        for doc_name, pdf_path in rows:
            if "user manual" in doc_name.lower() or "users manual" in doc_name.lower():
                return f"https://fcc.report{pdf_path}"
        for doc_name, pdf_path in rows:
            if "manual" in doc_name.lower():
                return f"https://fcc.report{pdf_path}"
        if rows:
            return f"https://fcc.report{rows[0][1]}"
    except Exception as exc:
        print(f"[ifu_finder] FCC scrape error: {exc}")
    return None


def _try_eudamed(di: str) -> Optional[str]:
    """
    Query EUDAMED (EU medical device database) for the device record.

    Currently EUDAMED's public API returns device metadata (manufacturer,
    risk class, EU registration status) but NOT IFU document URLs — the
    EU eIFU mandate (requiring manufacturers to register IFU links) is being
    phased in through May 2026. This function is groundwork: when EUDAMED
    adds labeling URLs to its API response, this will return them automatically.

    For now it returns None for the URL but logs the EU registration status,
    which is useful for validation (e.g. confirming the manufacturer name).
    """
    if not di:
        return None
    try:
        resp = requests.get(
            "https://ec.europa.eu/tools/eudamed/api/devices/udiDiData",
            params={"fullTextSearchValue": di, "page": 0, "pageSize": 5},
            timeout=TIMEOUT,
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("content") or []
        for item in items:
            if item.get("primaryDi") == di or item.get("basicUdi") == di:
                # Check for any labeling/document URL fields (future-proofing)
                for key in ("labelUrl", "ifu_url", "labellingUrl",
                            "electronicIfu", "labelingUrl"):
                    val = item.get(key)
                    if val and str(val).startswith("http"):
                        return val
                # Log EU registration for debugging
                mfr = item.get("manufacturerName", "")
                risk = (item.get("riskClass") or {}).get("code", "")
                print(f"[ifu_finder] EUDAMED: found EU record — {mfr} risk={risk}")
                return None
    except Exception as exc:
        print(f"[ifu_finder] EUDAMED exception: {exc}")
    return None


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

    # Step -1: offline manual library — instant, no network, never rate-limited.
    local = _try_local(manufacturer, brand, model)
    if local:
        url = local
        source = "local_manual"

    # Step 0: curated seed — instant, no network call
    curated = _try_curated(manufacturer, brand, model) if not url else None
    if curated:
        url, _fcc_id = curated
        source = "curated"
        print(f"[ifu_finder] curated hit: {_fcc_id} → {url}")

    if not url and di:
        url = _try_gudid_v3(di)
        if url:
            source = "gudid_v3"

    if not url and di:
        url = _try_gudid_v2(di)
        if url:
            source = "gudid_v2"

    if not url and di:
        url = _try_eudamed(di)
        if url:
            source = "eudamed"

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
