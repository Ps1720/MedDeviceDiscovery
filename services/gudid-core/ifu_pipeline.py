"""
IFU Pipeline — orchestrates find → extract → validate → store.

Programmatic API:
    from ifu_pipeline import run_pipeline
    result = run_pipeline(di="00643169634589", manufacturer="Medtronic",
                          brand="Azure XT DR", model="W1DR01")

CLI:
    python ifu_pipeline.py --di 00643169634589 --manufacturer Medtronic \\
                           --brand "Azure XT DR" --model W1DR01

    python ifu_pipeline.py --list          # show all stored IFU records
    python ifu_pipeline.py --verify 3 --by "Dr. Smith"  # mark record 3 verified

The pipeline always completes (it never raises). On partial failure the result
carries an "errors" list and partial data is stored so the record is visible in
the admin view for manual follow-up.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

import protocol_db
import ifu_finder
import ifu_extractor
import ifu_validator
import ifu_store

try:
    from device_class_resolver import resolve_class
    _RESOLVER_AVAILABLE = True
except ImportError:
    _RESOLVER_AVAILABLE = False


def _resolve_class_key(manufacturer: str, brand: str, model: str) -> Optional[str]:
    if not _RESOLVER_AVAILABLE:
        return None
    try:
        fhir_lite = {
            "manufacturer": manufacturer,
            "brandName": brand,
            "versionModelNumber": model,
            "gmdnTerms": {"gmdn": []},
            "productCodes": {"fdaProductCode": []},
        }
        result = resolve_class(fhir_lite)
        return result.class_key if result else None
    except Exception:
        return None


def run_pipeline(
    *,
    manufacturer: str,
    brand: str,
    model: str,
    di: Optional[str] = None,
    ifu_url: Optional[str] = None,
    gudid_record: Optional[dict] = None,
    verbose: bool = False,
) -> dict:
    """
    Run the full IFU pipeline for one device.

    Args:
        manufacturer:  e.g. "Medtronic"
        brand:         e.g. "Azure XT"
        model:         e.g. "DR MRI SureScan W1DR01"
        di:            Device Identifier — improves GUDID lookup (optional)
        ifu_url:       Provide a known PDF URL to skip the finder step
        gudid_record:  Pre-fetched GUDID record dict for validation (optional)
        verbose:       Print step-by-step progress

    Returns:
        {
          "di": str | None,
          "manufacturer": str,
          "brand": str,
          "model": str,
          "class_key": str | None,
          "finder": dict,
          "extraction": dict,
          "validation": dict,
          "store": dict,
          "errors": list[str],
          "summary": str,
        }
    """
    errors: list[str] = []

    def log(msg: str) -> None:
        if verbose:
            print(f"  {msg}")

    protocol_db.init_db()

    # ── Step 1: Resolve device class ────────────────────────────────────────
    log("Resolving device class...")
    class_key = _resolve_class_key(manufacturer, brand, model)
    log(f"  class_key = {class_key}")

    # ── Step 2: Find IFU URL ─────────────────────────────────────────────────
    if ifu_url:
        log(f"Using provided IFU URL: {ifu_url}")
        finder_result = {
            "url": ifu_url,
            "source": "provided",
            "search_query": f"{manufacturer} {brand} {model} IFU",
            "search_hint_url": "",
        }
    else:
        log("Finding IFU URL...")
        finder_result = ifu_finder.find_ifu(
            manufacturer=manufacturer,
            brand=brand,
            model=model,
            di=di,
        )
        log(f"  source={finder_result['source']}  url={finder_result['url']}")

    if not finder_result.get("url"):
        errors.append(
            f"IFU URL not found automatically. "
            f"Search manually: {finder_result.get('search_hint_url', '')}"
        )

    # ── Step 3: Extract from PDF ─────────────────────────────────────────────
    if finder_result.get("url"):
        log("Downloading and extracting PDF...")
        extraction_result = ifu_extractor.extract_from_url(finder_result["url"])
        if extraction_result.get("error"):
            errors.append(f"Extraction error: {extraction_result['error']}")
            log(f"  ERROR: {extraction_result['error']}")
        else:
            log(f"  Extracted {extraction_result['text_chars']} chars; "
                f"facts keys: {list((extraction_result.get('facts') or {}).keys())}")
    else:
        extraction_result = {
            "url": finder_result.get("url"),
            "ifu_hash": None,
            "text_chars": 0,
            "facts": None,
            "error": "No URL to extract from",
        }

    # ── Step 4: Validate against GUDID ──────────────────────────────────────
    log("Validating against GUDID...")
    gudid_rec = gudid_record or {}
    validation_result = ifu_validator.validate(
        facts=extraction_result.get("facts") or {},
        gudid_record=gudid_rec,
        manufacturer=manufacturer,
        brand=brand,
    )
    log(f"  valid={validation_result['valid']}  "
        f"confidence={validation_result['confidence']}  "
        f"conflicts={len(validation_result['conflicts'])}")

    for conflict in validation_result.get("conflicts", []):
        errors.append(f"Validation conflict: {conflict}")

    # ── Step 5: Store results ─────────────────────────────────────────────────
    log("Storing results...")
    store_result = ifu_store.save_pipeline_result(
        di=di,
        manufacturer=manufacturer,
        brand=brand,
        model=model,
        class_key=class_key,
        finder_result=finder_result,
        extraction_result=extraction_result,
        validation_result=validation_result,
    )
    log(f"  ifu_record_id={store_result['ifu_record_id']}  "
        f"brand_facts_written={store_result['brand_facts_written']}")

    # ── Summary ───────────────────────────────────────────────────────────────
    if errors:
        summary = (
            f"Completed with {len(errors)} issue(s). "
            f"IFU record #{store_result['ifu_record_id']} saved (status: {store_result['status']}). "
            f"brand_facts written: {store_result['brand_facts_written']}."
        )
    else:
        summary = (
            f"Success. IFU record #{store_result['ifu_record_id']} saved. "
            f"{store_result['brand_facts_written']} brand_facts written — "
            f"all require clinician verification before serving without VERIFY banner."
        )

    return {
        "di": di,
        "manufacturer": manufacturer,
        "brand": brand,
        "model": model,
        "class_key": class_key,
        "finder": finder_result,
        "extraction": extraction_result,
        "validation": validation_result,
        "store": store_result,
        "errors": errors,
        "summary": summary,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def _cmd_run(args: argparse.Namespace) -> None:
    print(f"\nRunning IFU pipeline for: {args.manufacturer} / {args.brand} / {args.model}")
    if args.di:
        print(f"  DI: {args.di}")
    result = run_pipeline(
        di=args.di,
        manufacturer=args.manufacturer,
        brand=args.brand,
        model=args.model,
        ifu_url=args.url,
        verbose=args.verbose,
    )
    print("\n── Summary ─────────────────────────────────────────")
    print(result["summary"])
    if result["errors"]:
        print("\n── Issues ──────────────────────────────────────────")
        for e in result["errors"]:
            print(f"  ! {e}")
    if result["finder"].get("search_hint_url"):
        print(f"\nManual search: {result['finder']['search_hint_url']}")
    facts = (result.get("extraction") or {}).get("facts") or {}
    if facts:
        print("\n── Extracted facts ─────────────────────────────────")
        for k, v in facts.items():
            if v is not None:
                print(f"  {k}: {v}")


def _cmd_list(_args: argparse.Namespace) -> None:
    protocol_db.init_db()
    records = protocol_db.list_ifu_records()
    if not records:
        print("No IFU records stored yet.")
        return
    print(f"\n{'ID':>4}  {'Status':<12}  {'Manufacturer':<20}  {'Brand':<20}  {'Last fetched':<20}  {'Conflicts'}")
    print("-" * 100)
    for r in records:
        conflicts = json.loads(r.get("conflict_flags") or "[]")
        conflict_str = f"{len(conflicts)} conflict(s)" if conflicts else "none"
        print(
            f"{r['id']:>4}  {(r.get('status') or ''):<12}  "
            f"{(r.get('manufacturer') or '')[:19]:<20}  "
            f"{(r.get('brand') or '')[:19]:<20}  "
            f"{(r.get('last_fetched') or '')[:19]:<20}  "
            f"{conflict_str}"
        )


def _cmd_verify(args: argparse.Namespace) -> None:
    protocol_db.init_db()
    ifu_store.mark_verified(args.verify, args.by)
    print(f"IFU record #{args.verify} marked verified by '{args.by}'.")
    print("All associated brand_facts now have requires_verification=0.")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="IFU Pipeline — find, extract, validate, and store IFU facts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--di", help="Device Identifier (DI) from GUDID")
    p.add_argument("--manufacturer", default="", help="Manufacturer name")
    p.add_argument("--brand", default="", help="Brand / device family name")
    p.add_argument("--model", default="", help="Model number")
    p.add_argument("--url", help="Provide the IFU PDF URL directly (skips finder)")
    p.add_argument("--list", action="store_true", help="List all stored IFU records")
    p.add_argument("--verify", type=int, metavar="ID", help="Mark IFU record ID as verified")
    p.add_argument("--by", default="", help="Verifier name (use with --verify)")
    p.add_argument("--verbose", action="store_true", help="Print step-by-step progress")
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.list:
        _cmd_list(args)
    elif args.verify:
        if not args.by:
            parser.error("--verify requires --by <name>")
        _cmd_verify(args)
    elif args.manufacturer or args.di:
        _cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
