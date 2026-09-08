"""
GUDID (Global Unique Device Identification Database) API Integration

This module connects to the FDA's AccessGUDID API to retrieve device information
based on UDI (Unique Device Identifier) or DI (Device Identifier).

API Documentation: https://accessgudid.nlm.nih.gov/resources/developers/device_lookup_api

IMPORTANT: This uses API v3. Make sure Config.GUDID_BASE_URL is set to:
           https://accessgudid.nlm.nih.gov/api/v3

FIXES:
- Normalized search_devices() to return consistent format
- Added robust None handling in extract_device_info()
- Better error logging
"""

import requests
from typing import Optional, Dict, Any, List
from config import Config


def _safe_get(obj: Any, *keys, default=None) -> Any:
    """
    Safely navigate nested dictionaries, handling None values.
    
    Example: _safe_get(data, "gudid", "device", "contacts", default={})
    """
    result = obj
    for key in keys:
        if result is None:
            return default
        if isinstance(result, dict):
            result = result.get(key)
        else:
            return default
    return result if result is not None else default


def parse_udi(udi: str) -> Optional[Dict[str, Any]]:
    """
    Parse a UDI string to extract its components.
    
    Args:
        udi: The full UDI barcode string
        
    Returns:
        Parsed UDI components including DI (Device Identifier) and PI (Production Identifier)
    """
    try:
        response = requests.get(
            f"{Config.GUDID_BASE_URL}/parse_udi.json",
            params={"udi": udi},
            timeout=Config.GUDID_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            # The v3 parse_udi API returns di/issuingAgency at the TOP level
            # (alongside an echoed "udi" string). Older shapes nested them under
            # "udi" -> handle both.
            if data and ("di" in data or "udi" in data):
                return {
                    "di": data.get("di") or _safe_get(data, "udi", "di"),
                    "issuing_agency": data.get("issuingAgency") or _safe_get(data, "udi", "issuingAgency"),
                    "raw": data,
                }
            return data
        else:
            print(f"GUDID Parse UDI error: {response.status_code}")
            return None
            
    except requests.RequestException as e:
        print(f"GUDID Parse UDI request failed: {e}")
        return None


def lookup_device_by_di(di: str) -> Optional[Dict[str, Any]]:
    """
    Look up a device in GUDID by its Device Identifier (DI).
    
    Args:
        di: The Device Identifier (numeric string, typically 14 digits)
        
    Returns:
        Raw GUDID API response containing device information
    """
    try:
        url = f"{Config.GUDID_BASE_URL}/devices/lookup.json"
        params = {"di": di}
        
        print(f"GUDID Lookup URL: {url}?di={di}")
        
        response = requests.get(url, params=params, timeout=Config.GUDID_TIMEOUT)
        
        print(f"GUDID Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            # Debug: print structure
            if data:
                print(f"GUDID Response Keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
            return data
        elif response.status_code == 404:
            print(f"Device not found in GUDID: {di}")
            return None
        else:
            print(f"GUDID lookup error: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            return None
            
    except requests.RequestException as e:
        print(f"GUDID lookup request failed: {e}")
        return None


def lookup_device_by_udi(udi: str) -> Optional[Dict[str, Any]]:
    """
    Look up a device in GUDID by its full UDI string.
    
    Args:
        udi: The full UDI barcode string
        
    Returns:
        Raw GUDID API response containing device information
    """
    try:
        response = requests.get(
            f"{Config.GUDID_BASE_URL}/devices/lookup.json",
            params={"udi": udi},
            timeout=Config.GUDID_TIMEOUT
        )
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"Device not found in GUDID: {udi}")
            return None
        else:
            print(f"GUDID lookup error: {response.status_code}")
            return None
            
    except requests.RequestException as e:
        print(f"GUDID lookup request failed: {e}")
        return None


def _extract_primary_di(device: Dict[str, Any]) -> Optional[str]:
    """
    Extract the primary Device Identifier from a GUDID device record.
    
    Args:
        device: The device object from GUDID response
        
    Returns:
        Primary DI string or None
    """
    if not device:
        return None
        
    identifiers = _safe_get(device, "identifiers", "identifier", default=[])
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    
    for ident in identifiers:
        if ident and ident.get("deviceIdType") == "Primary":
            return ident.get("deviceId")
    
    return None


def _normalize_lookup_to_search_format(data: Dict[str, Any], query: str) -> Dict[str, Any]:
    """
    Convert a GUDID lookup response to match search response format.
    
    This ensures consistent data structure whether using lookup (DI) or search (text).
    
    Args:
        data: Raw GUDID lookup response
        query: Original query string
        
    Returns:
        Normalized response with 'results' array
    """
    device = _safe_get(data, "gudid", "device", default={})
    
    if not device:
        print("No device found in GUDID response for normalization")
        return {"results": [], "totalCount": 0}
    
    primary_di = _extract_primary_di(device)
    
    # Extract GMDN terms for device type
    gmdn_terms = _safe_get(device, "gmdnTerms", "gmdn", default=[])
    if isinstance(gmdn_terms, dict):
        gmdn_terms = [gmdn_terms]
    
    gmdn_name = ""
    if gmdn_terms and len(gmdn_terms) > 0 and gmdn_terms[0]:
        gmdn_name = gmdn_terms[0].get("gmdnPTName", "")
    
    result = {
        "primaryDi": primary_di or query,
        "companyName": device.get("companyName", "") or "",
        "brandName": device.get("brandName", "") or "",
        "versionModelNumber": device.get("versionModelNumber", "") or "",
        "deviceDescription": device.get("deviceDescription", "") or "",
        "gmdnPTName": gmdn_name,
        "deviceCommDistributionStatus": device.get("deviceCommDistributionStatus", "") or "",
        "MRISafetyStatus": device.get("MRISafetyStatus", "") or "",
    }
    
    print(f"Normalized result: {result.get('brandName')} by {result.get('companyName')}")
    
    return {
        "results": [result],
        "totalCount": 1,
        "_raw": data  # Keep original for extract_device_info if needed
    }


def search_devices(query: str, limit: int = 10) -> Optional[Dict[str, Any]]:
    """
    Search for devices by Device ID or free text.

    - Numeric queries (Device IDs): AccessGUDID lookup API, normalized
    - Text queries: openFDA UDI feed (api.fda.gov/device/udi.json) — the
      AccessGUDID /devices/search.json endpoint was retired (404s as of
      2026-06) so text search goes through openFDA instead

    Always returns consistent format with 'results' array.

    Args:
        query: Device ID (numeric) or search text
        limit: Maximum number of results for text searches

    Returns:
        Normalized response with 'results' array containing matching devices
    """
    try:
        # Clean the query
        query = query.strip()

        # If the query is numeric (looks like a Device ID), use lookup
        if query.isdigit() and len(query) >= 10:
            url = f"{Config.GUDID_BASE_URL}/devices/lookup.json"
            params = {"di": query}

            print(f"GUDID Search Request: {url}")
            print(f"GUDID Search Params: {params}")

            response = requests.get(url, params=params, timeout=Config.GUDID_TIMEOUT)
            print(f"GUDID Search Response Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if "gudid" in data:
                    normalized = _normalize_lookup_to_search_format(data, query)
                    print(f"GUDID Normalized Results: {len(normalized.get('results', []))} device(s)")
                    return normalized
                print(f"Unexpected lookup response format: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            elif response.status_code == 404:
                print(f"Device not found in GUDID: {query}")
            else:
                print(f"GUDID error: {response.status_code}")
                print(f"Response: {response.text[:300]}")
            return {"results": [], "totalCount": 0}

        return _search_openfda_udi(query, limit)

    except requests.RequestException as e:
        print(f"GUDID request failed: {e}")
        return {"results": [], "totalCount": 0}


def _search_openfda_udi(query: str, limit: int = 10) -> Dict[str, Any]:
    """
    Free-text device search via the openFDA UDI feed, normalized to the same
    'results' shape the old AccessGUDID search returned.
    """
    url = "https://api.fda.gov/device/udi.json"
    params = {"search": query, "limit": max(1, min(limit, 50))}

    print(f"openFDA UDI Search Request: {url} params={params}")
    response = requests.get(url, params=params, timeout=Config.GUDID_TIMEOUT)
    print(f"openFDA UDI Search Response Status: {response.status_code}")

    if response.status_code == 404:
        # openFDA returns 404 with {"error": {"code": "NOT_FOUND"}} for no matches
        print(f"No devices found in openFDA UDI feed: {query}")
        return {"results": [], "totalCount": 0}
    if response.status_code != 200:
        print(f"openFDA error: {response.status_code}")
        print(f"Response: {response.text[:300]}")
        return {"results": [], "totalCount": 0}

    data = response.json()
    results = []
    for r in data.get("results", []):
        primary_di = next(
            (i.get("id") for i in r.get("identifiers", []) if i.get("type") == "Primary"),
            None,
        )
        if not primary_di:
            continue
        gmdn_terms = r.get("gmdn_terms") or []
        results.append({
            "primaryDi": primary_di,
            "companyName": r.get("company_name", "") or "",
            "brandName": r.get("brand_name", "") or "",
            "versionModelNumber": r.get("version_or_model_number", "") or "",
            "deviceDescription": r.get("device_description", "") or "",
            "gmdnPTName": (gmdn_terms[0].get("name", "") if gmdn_terms else "") or "",
            "deviceCommDistributionStatus": r.get("commercial_distribution_status", "") or "",
            "MRISafetyStatus": r.get("mri_safety", "") or "",
        })

    total = (data.get("meta", {}).get("results", {}) or {}).get("total", len(results))
    print(f"openFDA UDI Search Results: {len(results)} of {total} device(s)")
    return {"results": results, "totalCount": total}


def _as_bool(value: Any) -> Optional[bool]:
    """
    Normalise a GUDID boolean flag. The API returns these as real booleans in
    some records and as the strings "true"/"false" in others.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "y", "1"):
            return True
        if v in ("false", "no", "n", "0"):
            return False
    return None


def extract_device_info(gudid_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract relevant device information from GUDID API response.
    
    Transforms the raw GUDID response into a simplified format
    that matches our application's device structure.
    
    Args:
        gudid_response: Raw response from lookup_device_by_di or lookup_device_by_udi
        
    Returns:
        Simplified device dictionary with standardized fields
    """
    if not gudid_response:
        print("extract_device_info: No response to extract from")
        return {}
    
    try:
        # Handle both raw lookup response and normalized response
        if "_raw" in gudid_response:
            gudid_response = gudid_response["_raw"]
        
        device = _safe_get(gudid_response, "gudid", "device", default={})
        product_codes_extra = gudid_response.get("productCodes", [])
        
        if not device:
            print("extract_device_info: No device data in GUDID response")
            print(f"Response keys: {list(gudid_response.keys()) if isinstance(gudid_response, dict) else 'not a dict'}")
            return {}
        
        print(f"extract_device_info: Found device with keys: {list(device.keys())[:10]}...")
        
        # Extract primary device identifier
        primary_di = _extract_primary_di(device)
        
        # Extract GMDN (Global Medical Device Nomenclature) info
        gmdn_terms = _safe_get(device, "gmdnTerms", "gmdn", default=[])
        if isinstance(gmdn_terms, dict):
            gmdn_terms = [gmdn_terms]
        
        gmdn_info = []
        for term in (gmdn_terms or []):
            if term:
                gmdn_info.append({
                    "code": term.get("gmdnPTCode"),
                    "name": term.get("gmdnPTName"),
                    "definition": term.get("gmdnPTDefinition")
                })
        
        # Extract FDA product codes from device
        product_codes = _safe_get(device, "productCodes", "fdaProductCode", default=[])
        if isinstance(product_codes, dict):
            product_codes = [product_codes]
        
        fda_codes = []
        for code in (product_codes or []):
            if code:
                fda_codes.append({
                    "code": code.get("productCode"),
                    "name": code.get("productCodeName")
                })
        
        # Get device class from extra product codes
        device_class = ""
        if product_codes_extra and isinstance(product_codes_extra, list) and len(product_codes_extra) > 0:
            first_code = product_codes_extra[0]
            if first_code:
                device_class = first_code.get("deviceClass", "")
        
        # Extract customer contacts - with robust None handling
        contacts_data = _safe_get(device, "contacts", default={})
        contacts = []
        if contacts_data:
            customer_contacts = contacts_data.get("customerContact", [])
            if isinstance(customer_contacts, dict):
                customer_contacts = [customer_contacts]
            contacts = customer_contacts if customer_contacts else []
        
        contact_info = []
        for contact in (contacts or []):
            if contact:
                contact_info.append({
                    "phone": contact.get("phone"),
                    "email": contact.get("email")
                })
        
        # Extract sterilization info - with robust None handling
        sterilization = _safe_get(device, "sterilization", default={})
        is_sterile = None
        sterilization_prior = None
        if sterilization:
            is_sterile = sterilization.get("deviceSterile")
            sterilization_prior = sterilization.get("sterilizationPriorToUse")
        
        # Extract storage/environmental conditions - with robust None handling
        env_conditions = _safe_get(device, "environmentalConditions", default={})
        storage_handling = []
        if env_conditions:
            storage_handling = env_conditions.get("storageHandling", [])
            if isinstance(storage_handling, dict):
                storage_handling = [storage_handling]
            storage_handling = storage_handling if storage_handling else []
        
        storage_info = []
        for storage in (storage_handling or []):
            if storage:
                storage_info.append({
                    "type": storage.get("storageHandlingType"),
                    "high": storage.get("storageHandlingHigh", {}),
                    "low": storage.get("storageHandlingLow", {}),
                    "special": storage.get("storageHandlingSpecialConditionText")
                })
        
        # Build simplified device info
        device_info = {
            "id": primary_di,
            "source": "gudid",
            "manufacturer": device.get("companyName") or "Unknown",
            "brand_name": device.get("brandName") or "Unknown",
            "model": device.get("versionModelNumber") or "",
            "catalog_number": device.get("catalogNumber") or "",
            "description": device.get("deviceDescription") or "",
            "type": gmdn_info[0]["name"] if gmdn_info and gmdn_info[0].get("name") else "Medical Device",
            
            # Safety information
            "mri_safety": device.get("MRISafetyStatus") or "Unknown",
            "single_use": device.get("singleUse"),
            "sterile": is_sterile,
            "sterilization_prior_to_use": sterilization_prior,
            "contains_latex": device.get("labeledContainsNRL"),
            "no_latex": device.get("labeledNoNRL"),
            
            # Regulatory information
            "device_class": device_class,
            "rx": device.get("rx"),
            "otc": device.get("otc"),
            "premarket_exempt": device.get("premarketExempt", False),
            "commercial_status": device.get("deviceCommDistributionStatus") or "",
            
            # Device characteristics
            "device_count": device.get("deviceCount"),
            # GUDID's lotBatch / serialNumber / expirationDate / manufacturingDate
            # are BOOLEAN FLAGS — "does this device carry a lot number?" — not the
            # values themselves. The values are production identifiers that only
            # exist on the physical package and come from parsing the scanned UDI.
            # Reading them as values wrote serialNumber="True", lotNumber="False"
            # into every Device resource. Keep them, but named as the flags they are.
            "has_lot_batch": _as_bool(device.get("lotBatch")),
            "has_serial_number": _as_bool(device.get("serialNumber")),
            "has_expiration_date": _as_bool(device.get("expirationDate")),
            "has_manufacturing_date": _as_bool(device.get("manufacturingDate")),
            "combination_product": device.get("deviceCombinationProduct"),
            
            # Additional information
            "gmdn": gmdn_info,
            "fda_product_codes": fda_codes,
            "contacts": contact_info,
            "storage": storage_info,
            
            # Placeholders for local enrichment
            "features": [],
            "common_alarms": [],
            "quick_tips": []
        }
        
        # Add GMDN definition if available
        if gmdn_info and gmdn_info[0].get("definition"):
            device_info["gmdn_definition"] = gmdn_info[0]["definition"]
        
        print(f"extract_device_info: Successfully extracted {device_info.get('brand_name')}")
        return device_info
        
    except Exception as e:
        print(f"Error extracting device info: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_device_from_gudid(identifier: str, is_udi: bool = False) -> Optional[Dict[str, Any]]:
    """
    Main function to get device information from GUDID.
    
    Args:
        identifier: Device Identifier (DI) or full UDI string
        is_udi: If True, treats identifier as a full UDI; otherwise as DI
        
    Returns:
        Extracted device information dictionary or None if not found
    """
    print(f"Getting device from GUDID: {identifier} (is_udi={is_udi})")
    
    if is_udi:
        raw_response = lookup_device_by_udi(identifier)
    else:
        raw_response = lookup_device_by_di(identifier)
    
    if raw_response:
        device_info = extract_device_info(raw_response)
        if device_info and device_info.get("id"):
            print(f"Successfully extracted device: {device_info.get('brand_name', 'Unknown')}")
            return device_info
        else:
            print("Failed to extract device info from response")
    else:
        print("No response from GUDID lookup")
    
    return None


def get_device_summary(identifier: str) -> Optional[Dict[str, str]]:
    """
    Get a quick summary of device information (lightweight lookup).
    
    Args:
        identifier: Device Identifier (DI)
        
    Returns:
        Simple dictionary with key device info
    """
    result = search_devices(identifier, limit=1)
    
    if result and result.get("results"):
        device = result["results"][0]
        return {
            "id": device.get("primaryDi", identifier),
            "brand_name": device.get("brandName", ""),
            "manufacturer": device.get("companyName", ""),
            "model": device.get("versionModelNumber", ""),
            "description": (device.get("deviceDescription") or "")[:200],
            "type": device.get("gmdnPTName", "Medical Device")
        }
    
    return None


# ============================================
# Testing / CLI Usage
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("GUDID Service Test")
    print(f"API Base URL: {Config.GUDID_BASE_URL}")
    print("=" * 60)
    
    # Test devices
    test_devices = [
        ("00840682145596", "GE Carestation 750"),
        ("08717648200274", "Abbott XIENCE Alpine Stent"),
        ("00382903471874", "BD Syringe"),
    ]
    
    for test_di, expected_name in test_devices:
        print(f"\n{'=' * 60}")
        print(f"Testing: {test_di} (expected: {expected_name})")
        print("-" * 60)
        
        # Test search_devices (the function used by app.py search)
        print("\n1. Testing search_devices():")
        search_result = search_devices(test_di)
        if search_result and search_result.get("results"):
            result = search_result["results"][0]
            print(f"   ✓ Found via search_devices:")
            print(f"     - Brand: {result.get('brandName', 'N/A')}")
            print(f"     - Company: {result.get('companyName', 'N/A')}")
            print(f"     - Model: {result.get('versionModelNumber', 'N/A')}")
        else:
            print(f"   ✗ Not found via search_devices")
        
        # Test get_device_from_gudid (the function used by device page)
        print("\n2. Testing get_device_from_gudid():")
        device = get_device_from_gudid(test_di)
        if device:
            print(f"   ✓ Found via get_device_from_gudid:")
            print(f"     - Manufacturer: {device.get('manufacturer', 'N/A')}")
            print(f"     - Brand: {device.get('brand_name', 'N/A')}")
            print(f"     - Model: {device.get('model', 'N/A')}")
            print(f"     - Type: {device.get('type', 'N/A')}")
            print(f"     - MRI Safety: {device.get('mri_safety', 'N/A')}")
            print(f"     - Device Class: {device.get('device_class', 'N/A')}")
        else:
            print(f"   ✗ Not found via get_device_from_gudid")
    
    print(f"\n{'=' * 60}")
    print("Test complete!")
    print("=" * 60)