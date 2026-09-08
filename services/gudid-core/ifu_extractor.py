"""
IFU PDF downloader and clinical-fact extractor.

Steps:
  1. Download PDF from URL (with hash for change detection)
  2. Extract text via pdfplumber; focus on clinically relevant sections
  3. Send focused text to LLM for structured JSON extraction
  4. Return typed ExtractionResult

The LLM prompt is constrained to return only the JSON schema defined below;
all extracted values must be clinician-verified before use in the protocol layer.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.request import url2pathname

import requests

try:
    import pdfplumber
    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False

from config import Config
from openai import OpenAI

TIMEOUT = 30
MAX_CHARS_TO_LLM = 12_000  # keep within token budget

# Offline manual library (see ifu_finder.find_local_manual and app.serve_manual)
_MANUAL_URL_PREFIX = "/manuals/"
_MANUAL_DIR = Path(__file__).parent / "data" / "manuals"

# Keywords that mark a page as clinically relevant, weighted by how strongly
# each one predicts the facts we actually want.
#
# Weighting matters because pages are ranked, not taken in document order. Terms
# like "therapy" and "support" appear on nearly every page of a device manual —
# used as a plain filter they matched 212 of 312 pages of the LivaNova manual,
# which is no filter at all. They stay, but score close to nothing.
_KEYWORD_WEIGHTS = {
    # the facts we are extracting
    "magnet rate": 12.0, "magnet mode": 10.0, "magnet response": 10.0,
    "asynchronous": 8.0, "asynch": 6.0,
    "electrocautery": 10.0, "cautery": 8.0, "diathermy": 8.0,
    "magnetic resonance": 8.0, "mri": 6.0, "mr conditional": 10.0,
    "tesla": 6.0, "sar": 3.0, "gauss": 6.0,
    "electromagnetic interference": 8.0, "electromagnetic": 4.0,
    "bpm": 5.0, "beats per minute": 5.0,
    "24-hour": 5.0, "24 hour": 5.0, "1-800": 6.0, "1-866": 6.0, "1-877": 6.0,
    # weak signals — kept for recall, scored low so they cannot dominate
    "interference": 2.0, "inhibit": 2.0, "suspend": 2.0,
    "defibrillation": 2.0, "helpline": 3.0, "technical support": 2.0,
    "phone": 1.0, "support": 0.5, "therapy": 0.2,
}

# Retained for callers/tests that just want the term list.
_RELEVANT_KEYWORDS = list(_KEYWORD_WEIGHTS)

# Pages shorter than this are almost always contents entries or running headers.
_MIN_PAGE_CHARS = 220

# A pacing rate stated with its unit. Manufacturers are inconsistent: Medtronic
# writes "65 min-1", others "85 bpm", "100 ppm" or "beats per minute".
_RATE_PATTERN = re.compile(
    r"\b\d{2,3}\s*(?:min\s*[-–−]?\s*1|min⁻¹|bpm|ppm|beats\s*/?\s*min|beats per minute)",
    re.I,
)

_EXTRACTION_PROMPT = """You are a medical-device IFU parser. Extract perioperative-relevant facts from the text below.

Return ONLY a single JSON object with these keys (use null when not found):
{
  "magnet_rate_bpm": "numeric pacing rate during magnet application, e.g. '65'",
  "magnet_mode": "pacing mode during magnet application, e.g. 'DOO' or 'asynchronous'",
  "magnet_response_programmable_off": true | false | null,
  "magnet_inhibits_tachy_therapy": true | false | null,
  "mri_conditional": true | false | null,
  "mri_conditions_summary": "≤60-word summary of MRI conditions or null",
  "support_phone_24hr": "24-hour clinical/technical support phone number or null",
  "electrocautery_recommendation": "≤80-word key electrocautery guidance or null",
  "em_interference_notes": "≤80-word other EMI notes or null"
}

Do NOT add any text outside the JSON object.

IFU TEXT:
"""


def _get_llm_client() -> Optional[OpenAI]:
    if not Config.OPENAI_API_KEY:
        return None
    return OpenAI(api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_API_BASE)


def _download_pdf(source: str) -> tuple[Optional[bytes], Optional[str]]:
    """
    Load a PDF from an http(s) URL, a file:// URL, or a local filesystem path.

    Local sources matter because the offline manual library (data/manuals/)
    hands back a path — reading it directly avoids the app having to make an
    HTTP request to itself, which would need a correct host/port inside Docker.

    Returns (pdf_bytes, sha256_hex) or (None, None).
    """
    try:
        if source.startswith("file://"):
            source = url2pathname(urlparse(source).path)

        # "/manuals/<file>" is how the offline library refers to a manual
        # everywhere (DB, API, UI links). Resolve it to the file on disk rather
        # than making the app issue an HTTP request to itself.
        if source.startswith(_MANUAL_URL_PREFIX):
            name = source[len(_MANUAL_URL_PREFIX):].split("?")[0]
            candidate = (_MANUAL_DIR / name).resolve()
            if candidate.parent != _MANUAL_DIR.resolve() or not candidate.is_file():
                print(f"[ifu_extractor] manual not in library: {source}")
                return None, None
            source = str(candidate)

        if not source.startswith(("http://", "https://")):
            path = Path(source)
            if not path.is_file():
                print(f"[ifu_extractor] local PDF not found: {source}")
                return None, None
            content = path.read_bytes()
        else:
            resp = requests.get(
                source, timeout=TIMEOUT, headers={"User-Agent": "PeriopUDI/1.0"}
            )
            if resp.status_code != 200:
                return None, None
            content = resp.content

        if not content.startswith(b"%PDF"):
            print(f"[ifu_extractor] not a PDF (got {content[:16]!r}): {source}")
            return None, None
        return content, hashlib.sha256(content).hexdigest()
    except Exception as exc:  # noqa: BLE001
        print(f"[ifu_extractor] load failed: {exc}")
        return None, None


def _extract_relevant_text(pdf_bytes: bytes) -> str:
    """
    Return the most clinically relevant text from the PDF, within the token budget.

    Pages are RANKED by weighted keyword score, not taken in document order.
    Document order fails badly on long manuals: the LivaNova VNS physician's
    manual has 212 keyword-matching pages out of 312, so an in-order scan spent
    the entire 12,000-character budget on the title page and table of contents
    and the model saw no magnet rate, no MRI conditions and no support number.

    Selected pages are re-sorted into document order before joining, so the
    model still reads them in their natural sequence.
    """
    if not _PDF_AVAILABLE:
        raise RuntimeError(
            "pdfplumber is not installed. Run: pip install pdfplumber"
        )

    pages: list[tuple[int, str]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages):
            pages.append((idx, page.extract_text() or ""))

    def score(text: str) -> float:
        low = text.lower()
        if len(low) < _MIN_PAGE_CHARS:
            return 0.0          # contents entries, running headers, blank pages
        total = 0.0
        for kw, weight in _KEYWORD_WEIGHTS.items():
            hits = low.count(kw)
            if hits:
                # diminishing returns: a page repeating one term is not better
                # than a page covering several
                total += weight * (1 + min(hits - 1, 3) * 0.35)

        # A page stating an actual pacing rate is the single most valuable page
        # in the document, and keyword counting alone does not find it: the
        # Medtronic Azure manual writes "65 min-1", never "bpm", so the page
        # carrying the magnet rate ranked 7th and fell outside the budget.
        # Reward a number adjacent to any rate unit, and reward it more when
        # "magnet" appears on the same page.
        if _RATE_PATTERN.search(low):
            total += 25.0 if "magnet" in low else 10.0

        # normalise by length so a dense half-page beats a sprawling one
        return total / (1 + len(low) / 4000.0)

    ranked = sorted(
        ((score(t), i, t) for i, t in pages if t.strip()),
        key=lambda r: -r[0],
    )
    scored = [r for r in ranked if r[0] > 0]
    if not scored:
        scored = ranked  # nothing matched — fall back to whatever the PDF has

    # Take highest-scoring pages until the budget is spent, then restore order.
    picked: list[tuple[int, str]] = []
    used = 0
    for s, i, text in scored:
        if used + len(text) > MAX_CHARS_TO_LLM and picked:
            continue          # skip this one, a shorter page may still fit
        picked.append((i, text))
        used += len(text) + 2
        if used >= MAX_CHARS_TO_LLM:
            break

    picked.sort(key=lambda p: p[0])
    combined = "\n\n".join(t for _, t in picked)
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    return combined[:MAX_CHARS_TO_LLM]


# Evidence each fact must be able to point at in the source text before it may
# be stored and badged "Extracted from IFU".
#
# This exists because the model fabricated a clinically plausible electrocautery
# recommendation for the Medtronic Azure manual — a document containing zero
# occurrences of "electrocautery", "cautery" or "tachytherapy" — and it was
# stored with manufacturer attribution alongside genuinely extracted facts. A
# fabricated fact sitting next to true ones inherits their credibility, which is
# precisely the failure mode a clinician cannot detect.
#
# Each entry lists substrings, ANY of which must appear in the source text for
# the fact to be considered grounded.
# Keyed by BOTH the LLM's extraction key and the stored brand_facts key
# (ifu_store._FACT_KEY_MAP renames them on the way in), so the same rules apply
# whether checking fresh output or auditing what is already in the database.
_REQUIRED_EVIDENCE = {
    # extraction keys
    "electrocautery_recommendation": ("cauter", "electrosurg", "diathermy", "esu"),
    "em_interference_notes":         ("electromagnetic", "emi", "interference"),
    "mri_conditional":               ("mri", "magnetic resonance", "mr conditional"),
    "mri_conditions_summary":        ("mri", "magnetic resonance", "mr conditional"),
    "magnet_mode":                   ("magnet",),
    "magnet_response_programmable_off": ("magnet",),
    "magnet_inhibits_tachy_therapy": ("magnet",),
    "magnet_rate_bpm":               ("magnet",),
    # stored keys
    "electrocautery":                ("cauter", "electrosurg", "diathermy", "esu"),
    "em_interference":               ("electromagnetic", "emi", "interference"),
    "mri_conditions":                ("mri", "magnetic resonance", "mr conditional"),
    "magnet_programmable_off":       ("magnet",),
    "magnet_inhibits_therapy":       ("magnet",),
    "magnet_rate":                   ("magnet",),
}

# Fact keys whose value is a number that must appear verbatim in the source.
_NUMERIC_EVIDENCE_KEYS = (
    "magnet_rate_bpm", "magnet_rate", "support_phone_24hr", "support_phone",
)


def _is_grounded(key: str, value, source_text: str) -> bool:
    """
    True when `value` is actually supported by the source document.

    Numbers must appear verbatim; free-text facts must be accompanied by at
    least one of the domain terms the claim depends on. A fact that cannot point
    at its evidence is dropped rather than stored with a false citation.
    """
    if value is None or value == "":
        return True                      # nothing claimed, nothing to ground
    low = source_text.lower()

    # Numeric claims (magnet rate, phone number): the digits must be present.
    digits = re.findall(r"\d[\d\-\.]{1,}", str(value))
    if digits and key in _NUMERIC_EVIDENCE_KEYS:
        core = max(digits, key=len).replace("-", "").replace(".", "")
        stripped = re.sub(r"[^0-9]", "", low)
        return core in stripped

    needles = _REQUIRED_EVIDENCE.get(key)
    if not needles:
        return True                      # no evidence rule defined for this key

    # Short needles are abbreviations and must match whole words. As bare
    # substrings they produce false evidence: "esu" matches "result"/"resume",
    # "emi" matches "chemistry" — which is how a fabricated electrocautery
    # recommendation was accepted as grounded in a manual that never mentions
    # cautery at all.
    for n in needles:
        if len(n) <= 4:
            if re.search(rf"\b{re.escape(n)}\b", low):
                return True
        elif n in low:
            return True
    return False


def _drop_ungrounded(facts: dict, source_text: str) -> tuple[dict, list[str]]:
    """Remove facts the source text does not support. Returns (kept, dropped)."""
    kept, dropped = {}, []
    for key, value in (facts or {}).items():
        if _is_grounded(key, value, source_text):
            kept[key] = value
        else:
            dropped.append(key)
            print(f"[ifu_extractor] DROPPED ungrounded {key}={str(value)[:60]!r} "
                  f"— no supporting evidence in the source document")
    return kept, dropped


def _call_llm(text: str) -> Optional[dict]:
    client = _get_llm_client()
    if not client:
        print("[ifu_extractor] no LLM client — OPENAI_API_KEY not set")
        return None
    try:
        resp = client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a medical device IFU parser. "
                        "Output ONLY a valid JSON object — no thinking, no explanation, no markdown."
                    ),
                },
                {"role": "user", "content": _EXTRACTION_PROMPT + text},
            ],
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        original = raw

        # Strip Qwen3 / reasoning-model thinking blocks
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Strip markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

        # If the response is empty after stripping (model put everything in <think>),
        # pull the first {...} JSON object found anywhere in the original response.
        if not raw:
            match = re.search(r"\{.*\}", original, re.DOTALL)
            if match:
                raw = match.group(0)

        if not raw:
            print("[ifu_extractor] LLM returned empty content after cleanup")
            return None

        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[ifu_extractor] LLM returned non-JSON: {exc}")
        return None
    except Exception as exc:
        print(f"[ifu_extractor] LLM call failed: {exc}")
        return None


def extract_from_url(url: str) -> dict:
    """
    Download the PDF at `url`, extract relevant text, and run LLM extraction.

    Returns:
        {
          "url": str,
          "ifu_hash": str | None,
          "text_chars": int,
          "facts": dict | None,   # LLM output, None on failure
          "error": str | None,
        }
    """
    pdf_bytes, ifu_hash = _download_pdf(url)
    if not pdf_bytes:
        return {"url": url, "ifu_hash": None, "text_chars": 0, "facts": None,
                "error": "PDF download failed"}

    try:
        text = _extract_relevant_text(pdf_bytes)
    except RuntimeError as exc:
        return {"url": url, "ifu_hash": ifu_hash, "text_chars": 0, "facts": None,
                "error": str(exc)}

    if not text.strip():
        return {"url": url, "ifu_hash": ifu_hash, "text_chars": 0, "facts": None,
                "error": "No text extracted from PDF"}

    facts = _call_llm(text)
    dropped: list[str] = []
    if facts:
        facts, dropped = _drop_ungrounded(facts, text)
    return {
        "ungrounded_dropped": dropped,
        "url": url,
        "ifu_hash": ifu_hash,
        "text_chars": len(text),
        "facts": facts,
        "error": None if facts is not None else "LLM extraction returned no result",
    }
