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
from typing import Optional

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

# Keywords that flag a page as clinically relevant for perioperative use
_RELEVANT_KEYWORDS = [
    "magnet", "asynchronous", "asynch", "electrocautery", "cautery",
    "electromagnetic", "interference", "mri", "magnetic resonance",
    "support", "helpline", "technical support", "phone",
    "defibrillation", "therapy", "inhibit", "suspend",
]

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


def _download_pdf(url: str) -> tuple[Optional[bytes], Optional[str]]:
    """Returns (pdf_bytes, sha256_hex) or (None, None)."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "PeriopUDI/1.0"})
        if resp.status_code != 200:
            return None, None
        content = resp.content
        sha256 = hashlib.sha256(content).hexdigest()
        return content, sha256
    except Exception as exc:
        print(f"[ifu_extractor] download failed: {exc}")
        return None, None


def _extract_relevant_text(pdf_bytes: bytes) -> str:
    """
    Parse PDF and return text from pages that contain clinically relevant keywords.
    Falls back to full text if no keyword pages found.
    """
    if not _PDF_AVAILABLE:
        raise RuntimeError(
            "pdfplumber is not installed. Run: pip install pdfplumber"
        )

    relevant_pages: list[str] = []
    all_pages: list[str] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_pages.append(text)
            lower = text.lower()
            if any(kw in lower for kw in _RELEVANT_KEYWORDS):
                relevant_pages.append(text)

    chosen = relevant_pages if relevant_pages else all_pages
    combined = "\n\n".join(chosen)
    # Collapse excessive whitespace and trim to budget
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    return combined[:MAX_CHARS_TO_LLM]


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
    return {
        "url": url,
        "ifu_hash": ifu_hash,
        "text_chars": len(text),
        "facts": facts,
        "error": None if facts is not None else "LLM extraction returned no result",
    }
