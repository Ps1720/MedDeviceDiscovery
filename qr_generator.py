"""
QR Code Generator for Medical Device Discovery

Generates QR codes that encode URLs pointing to device information pages.
When scanned with a phone camera, these QR codes open the device page
in the user's browser without requiring any app installation.
"""

import qrcode
from pathlib import Path
from config import Config


def generate_qr_code(device_id: str, save_path: str = None) -> str:
    """
    Generate a QR code for a device that points to the device page.
    
    Args:
        device_id: The unique identifier for the device
        save_path: Optional custom save path
    
    Returns:
        Path to the generated QR code image
    """
    # Build the URL that the QR code will contain
    url = f"{Config.BASE_URL}/device/{device_id}"
    
    # Create QR code with good error correction
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    # Create image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Ensure directory exists and save
    if save_path is None:
        Path(Config.QR_CODE_DIR).mkdir(parents=True, exist_ok=True)
        save_path = f"{Config.QR_CODE_DIR}/{device_id}.png"
    
    img.save(save_path)
    
    return save_path


def get_qr_code_path(device_id: str) -> str:
    """
    Get the path to a device's QR code, generating if it doesn't exist.
    
    Args:
        device_id: The unique identifier for the device
        
    Returns:
        Path to the QR code image
    """
    path = f"{Config.QR_CODE_DIR}/{device_id}.png"
    
    if not Path(path).exists():
        generate_qr_code(device_id)
    
    return path


def generate_all_qr_codes(devices: dict) -> dict:
    """
    Generate QR codes for all devices in a dictionary.
    
    Args:
        devices: Dictionary of device_id -> device_info
        
    Returns:
        Dictionary of device_id -> qr_code_path
    """
    results = {}
    for device_id in devices.keys():
        path = generate_qr_code(device_id)
        results[device_id] = path
        print(f"Generated QR code for {device_id}: {path}")
    return results


# ============================================
# Testing / CLI Usage
# ============================================

if __name__ == "__main__":
    # Test QR code generation
    test_device = "test_device_001"
    
    print(f"Generating QR code for: {test_device}")
    print(f"URL will be: {Config.BASE_URL}/device/{test_device}")
    
    path = generate_qr_code(test_device)
    print(f"QR code saved to: {path}")
