"""
GUDID (Global Unique Device Identification Database) API Integration

This module connects to the FDA's AccessGUDID API to retrieve device information
based on UDI (Unique Device Identifier) or DI (Device Identifier).

API Documentation: https://accessgudid.nlm.nih.gov/resources/developers/device_lookup_api
"""

import requests
from typing import Optional, Dict, Any
from config import Config


def parse_udi(udi: str) -> Optional[Dict[str, Any]]:
    """
    Parse a UDI string to extract its components.
    """
    try:
        response = requests.get(
            f"{Config.GUDID_BASE_URL}/parse_udi.json",
            params={"udi": udi},
            timeout=Config.GUDID_TIMEOUT
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"GUDID Parse UDI error: {response.status_code}")
            return None
            
    except requests.RequestException as e:
        print(f"GUDID Parse UDI request failed: {e}")
        return None


def lookup_device_by_di(di: str) -> Optional[Dict[str, Any]]:
    """
    Look up a device in GUDID by its Device Identifier (DI).
    """
    try:
        response = requests.get(
            f"{Config.GUDID_BASE_URL}/devices/lookup.json",
            params={"di": di},
            timeout=Config.GUDID_TIMEOUT
        )
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"Device not found in GUDID: {di}")
            return None
        else:
            print(f"GUDID lookup error: {response.status_code}")
            return None
            
    except requests.RequestException as e:
        print(f"GUDID lookup request failed: {e}")
        return None


def lookup_device_by_udi(udi: str) -> Optional[Dict[str, Any]]:
    """
    Look up a device in GUDID by its full UDI string.
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


def search_devices(query: str, limit: int = 10) -> Optional[Dict[str, Any]]:
    """
    Search for devices in GUDID.
    """
    try:
        # If the query is numeric, use lookup by DI
        if query.isdigit():
            url = f"{Config.GUDID_BASE_URL}/devices/lookup.json"
            params = {"di": query}
        else:
            url = f"{Config.GUDID_BASE_URL}/devices/search.json"
            params = {"search": query, "pageSize": limit}

        response = requests.get(url, params=params, timeout=Config.GUDID_TIMEOUT)

        print("GUDID URL:", response.url)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"GUDID error: {response.status_code}")
            return None

    except requests.RequestException as e:
        print(f"GUDID request failed: {e}")
        return None


def extract_device_info(gudid_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract relevant device information from GUDID API response.
    
    Transforms the raw GUDID response into a simplified format
    that matches our application's device structure.
    """
    if not gudid_response:
        return {}
    
    try:
        device = gudid_response.get("gudid", {}).get("device", {})
        product_codes_extra = gudid_response.get("productCodes", [])
        
        # Extract primary device identifier
        identifiers = device.get("identifiers", {}).get("identifier", [])
        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        
        primary_di = None
        for ident in identifiers:
            if ident.get("deviceIdType") == "Primary":
                primary_di = ident.get("deviceId")
                break
        
        # Extract GMDN (Global Medical Device Nomenclature) info
        gmdn_terms = device.get("gmdnTerms", {}).get("gmdn", [])
        if isinstance(gmdn_terms, dict):
            gmdn_terms = [gmdn_terms]
        
        gmdn_info = []
        for term in gmdn_terms:
            gmdn_info.append({
                "code": term.get("gmdnPTCode"),
                "name": term.get("gmdnPTName"),
                "definition": term.get("gmdnPTDefinition")
            })
        
        # Extract FDA product codes from device
        product_codes = device.get("productCodes", {}).get("fdaProductCode", [])
        if isinstance(product_codes, dict):
            product_codes = [product_codes]
        
        fda_codes = []
        for code in product_codes:
            fda_codes.append({
                "code": code.get("productCode"),
                "name": code.get("productCodeName")
            })
        
        # Get device class from extra product codes
        device_class = ""
        if product_codes_extra:
            device_class = product_codes_extra[0].get("deviceClass", "")
        
        # Extract customer contacts
        contacts = device.get("contacts", {}).get("customerContact", [])
        if isinstance(contacts, dict):
            contacts = [contacts]
        
        contact_info = []
        for contact in contacts:
            contact_info.append({
                "phone": contact.get("phone"),
                "email": contact.get("email")
            })
        
        # Extract sterilization info
        sterilization = device.get("sterilization", {})
        is_sterile = sterilization.get("deviceSterile") if sterilization else None
        sterilization_prior = sterilization.get("sterilizationPriorToUse") if sterilization else None
        
        # Extract storage/environmental conditions
        env_conditions = device.get("environmentalConditions", {})
        storage_handling = env_conditions.get("storageHandling", []) if env_conditions else []
        if isinstance(storage_handling, dict):
            storage_handling = [storage_handling]
        
        storage_info = []
        for storage in storage_handling:
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
            "manufacturer": device.get("companyName", "Unknown"),
            "brand_name": device.get("brandName", "Unknown"),
            "model": device.get("versionModelNumber", ""),
            "catalog_number": device.get("catalogNumber", ""),
            "description": device.get("deviceDescription", ""),
            "type": gmdn_info[0]["name"] if gmdn_info else "Medical Device",
            
            # Safety information
            "mri_safety": device.get("MRISafetyStatus", "Unknown"),
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
            "commercial_status": device.get("deviceCommDistributionStatus", ""),
            
            # Device characteristics
            "device_count": device.get("deviceCount"),
            "lot_batch": device.get("lotBatch"),
            "serial_number": device.get("serialNumber"),
            "expiration_date": device.get("expirationDate"),
            "manufacturing_date": device.get("manufacturingDate"),
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
        
        return device_info
        
    except Exception as e:
        print(f"Error extracting device info: {e}")
        return {}


def get_device_from_gudid(identifier: str, is_udi: bool = False) -> Optional[Dict[str, Any]]:
    """
    Main function to get device information from GUDID.
    """
    if is_udi:
        raw_response = lookup_device_by_udi(identifier)
    else:
        raw_response = lookup_device_by_di(identifier)
    
    if raw_response:
        return extract_device_info(raw_response)
    
    return None


# ============================================
# Testing / CLI Usage
# ============================================

if __name__ == "__main__":
    test_di = "08717648200274"  # Abbott XIENCE stent
    
    print(f"Looking up device: {test_di}")
    print("-" * 50)
    
    device = get_device_from_gudid(test_di)
    
    if device:
        print(f"✓ Found device in GUDID:")
        print(f"  Manufacturer: {device['manufacturer']}")
        print(f"  Brand: {device['brand_name']}")
        print(f"  Model: {device['model']}")
        print(f"  Type: {device['type']}")
        print(f"  MRI Safety: {device['mri_safety']}")
        print(f"  Single Use: {device['single_use']}")
        print(f"  Device Class: {device['device_class']}")
        print(f"  Sterile: {device['sterile']}")
        print(f"  Contacts: {device['contacts']}")
        print(f"  Storage: {device['storage']}")
    else:
        print("✗ Device not found")