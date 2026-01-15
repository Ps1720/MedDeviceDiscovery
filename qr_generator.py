"""
QR Code Generator for Medical Device Discovery

Generates QR codes that encode URLs pointing to device information pages.
When scanned with a phone camera, these QR codes open the device page
in the user's browser without requiring any app installation.

Now with database integration for tracking generated codes.
Includes file-based caching to avoid regenerating existing QR codes.
"""

import qrcode
from pathlib import Path
from config import Config
from database_setup import create_connection, add_qr_code, get_qr_code


def generate_qr_code(device_id: str, device_name: str = None,
                     manufacturer: str = None, category: str = 'Uncategorized',
                     device_type: str = None, source: str = 'manual',
                     save_to_db: bool = True, force: bool = False) -> dict:
    """
    Generate a QR code for a device that points to the device page.
    Uses file-based caching - only generates if file doesn't exist or force=True.
    
    Args:
        device_id: The unique identifier for the device
        device_name: Human-readable name of the device
        manufacturer: Device manufacturer
        category: Category for grouping (e.g., 'Cardiovascular', 'Orthopedic')
        device_type: Type of device (e.g., 'Stent', 'Pacemaker')
        source: Source of the device info ('manual', 'gudid', 'local')
        save_to_db: Whether to save the record to the database
        force: Force regeneration even if file exists
    
    Returns:
        Dictionary with QR code info: {device_id, qr_path, qr_url, device_url, saved_to_db, from_cache}
    """
    # Sanitize device_id
    clean_device_id = device_id.strip().replace(" ", "_")
    
    # Build the URL that the QR code will contain
    device_url = f"{Config.BASE_URL}/device/{clean_device_id}"
    
    # Ensure directory exists
    qr_dir = Path(Config.QR_CODE_DIR)
    qr_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if file already exists (CACHING)
    file_path = qr_dir / f"{clean_device_id}.png"
    from_cache = False
    
    if file_path.exists() and not force:
        # QR code already exists on disk - use cached version
        from_cache = True
        print(f"Using cached QR code for {clean_device_id}: {file_path}")
    else:
        # Generate new QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(device_url)
        qr.make(fit=True)
        
        # Create and save image
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(str(file_path))
        print(f"Generated new QR code for {clean_device_id}: {file_path}")
    
    # Relative path for serving
    qr_code_path = f"/static/qr_codes/{clean_device_id}.png"
    qr_url = f"/qr/{clean_device_id}"
    
    result = {
        'device_id': clean_device_id,
        'qr_path': str(file_path),
        'qr_code_path': qr_code_path,
        'qr_url': qr_url,
        'device_url': device_url,
        'saved_to_db': False,
        'from_cache': from_cache
    }
    
    # Save to database if requested
    if save_to_db:
        conn = create_connection()
        try:
            # Check if already exists in database
            existing = get_qr_code(conn, clean_device_id)
            if not existing:
                record_id = add_qr_code(
                    conn,
                    device_id=clean_device_id,
                    device_name=device_name or clean_device_id.replace("_", " ").title(),
                    manufacturer=manufacturer,
                    category=category,
                    device_type=device_type,
                    qr_code_path=qr_code_path,
                    source=source
                )
                result['saved_to_db'] = record_id > 0
                result['db_id'] = record_id
            else:
                result['saved_to_db'] = True
                result['db_id'] = existing.get('id')
                result['already_existed'] = True
        finally:
            conn.close()
    
    return result


def get_or_create_qr_code(device_id: str, device_info: dict = None) -> dict:
    """
    Get an existing QR code or create a new one.
    Checks both database and file system for caching.
    
    Args:
        device_id: The unique identifier for the device
        device_info: Optional dict with device details (name, manufacturer, category, etc.)
    
    Returns:
        Dictionary with QR code info from database or newly created
    """
    clean_device_id = device_id.strip().replace(" ", "_")
    file_path = Path(Config.QR_CODE_DIR) / f"{clean_device_id}.png"
    
    conn = create_connection()
    try:
        # Check if QR code already exists in database
        existing = get_qr_code(conn, clean_device_id)
        
        if existing:
            # Record exists in database
            if not file_path.exists():
                # File missing - regenerate image only (not db record)
                print(f"Database record exists but file missing for {clean_device_id}, regenerating image...")
                generate_qr_code(clean_device_id, save_to_db=False, force=True)
            else:
                print(f"Using cached QR code from database for {clean_device_id}")
            
            return {
                'device_id': clean_device_id,
                'qr_url': f"/qr/{clean_device_id}",
                'qr_code_path': existing.get('qr_code_path'),
                'device_url': f"{Config.BASE_URL}/device/{clean_device_id}",
                'device_name': existing.get('device_name'),
                'manufacturer': existing.get('manufacturer'),
                'category': existing.get('category'),
                'from_db': True,
                'from_cache': True
            }
        
        # Check if file exists even without database record
        if file_path.exists():
            print(f"File exists but no database record for {clean_device_id}, creating record...")
            # File exists but no DB record - create DB record without regenerating file
            info = device_info or {}
            return generate_qr_code(
                device_id=clean_device_id,
                device_name=info.get('device_name') or info.get('brand_name'),
                manufacturer=info.get('manufacturer'),
                category=info.get('category', 'Uncategorized'),
                device_type=info.get('type') or info.get('device_type'),
                source=info.get('source', 'manual'),
                force=False  # Don't regenerate - file already exists
            )
        
        # Nothing exists - create new QR code
        print(f"Creating new QR code for {clean_device_id}")
        info = device_info or {}
        return generate_qr_code(
            device_id=clean_device_id,
            device_name=info.get('device_name') or info.get('brand_name'),
            manufacturer=info.get('manufacturer'),
            category=info.get('category', 'Uncategorized'),
            device_type=info.get('type') or info.get('device_type'),
            source=info.get('source', 'manual')
        )
    finally:
        conn.close()


def get_qr_code_path(device_id: str) -> str:
    """
    Get the path to a device's QR code, generating if it doesn't exist.
    This is the main entry point for serving QR code images.
    
    Args:
        device_id: The unique identifier for the device
        
    Returns:
        Path to the QR code image
    """
    clean_device_id = device_id.strip().replace(" ", "_")
    path = Path(Config.QR_CODE_DIR) / f"{clean_device_id}.png"
    
    if path.exists():
        # File exists - return immediately (fastest path)
        return str(path)
    
    # File doesn't exist - generate it
    # Use get_or_create_qr_code to also ensure database record exists
    get_or_create_qr_code(clean_device_id)
    
    return str(path)


def qr_code_exists(device_id: str) -> dict:
    """
    Check if a QR code exists (both file and database).
    
    Args:
        device_id: The unique identifier for the device
        
    Returns:
        Dictionary with existence info: {file_exists, db_exists, device_id}
    """
    clean_device_id = device_id.strip().replace(" ", "_")
    file_path = Path(Config.QR_CODE_DIR) / f"{clean_device_id}.png"
    
    conn = create_connection()
    try:
        existing = get_qr_code(conn, clean_device_id)
        return {
            'device_id': clean_device_id,
            'file_exists': file_path.exists(),
            'db_exists': existing is not None,
            'file_path': str(file_path) if file_path.exists() else None,
            'db_record': existing
        }
    finally:
        conn.close()


def generate_all_qr_codes(devices: dict, category_map: dict = None) -> dict:
    """
    Generate QR codes for all devices in a dictionary.
    Skips devices that already have QR codes (uses caching).
    
    Args:
        devices: Dictionary of device_id -> device_info
        category_map: Optional mapping of device types to categories
        
    Returns:
        Dictionary of device_id -> qr_code_info
    """
    results = {}
    
    # Default category mapping based on device type
    default_category_map = {
        'stent': 'Cardiovascular',
        'pacemaker': 'Cardiovascular',
        'defibrillator': 'Cardiovascular',
        'lvad': 'Cardiovascular',
        'catheter': 'Cardiovascular',
        'hip': 'Orthopedic',
        'knee': 'Orthopedic',
        'spine': 'Orthopedic',
        'bone': 'Orthopedic',
        'joint': 'Orthopedic',
        'infusion': 'Infusion & IV',
        'pump': 'Infusion & IV',
        'syringe': 'Infusion & IV',
        'iv': 'Infusion & IV',
        'monitor': 'Monitoring',
        'ventilator': 'Respiratory',
        'airway': 'Respiratory',
        'imaging': 'Imaging',
        'surgical': 'Surgical',
        'implant': 'Surgical',
    }
    
    category_map = category_map or default_category_map
    
    generated_count = 0
    cached_count = 0
    
    for device_id, device in devices.items():
        # Determine category from device type or description
        category = 'Uncategorized'
        device_type = device.get('type', '').lower()
        description = device.get('description', '').lower()
        
        for keyword, cat in category_map.items():
            if keyword in device_type or keyword in description:
                category = cat
                break
        
        result = generate_qr_code(
            device_id=device_id,
            device_name=device.get('brand_name') or device.get('model'),
            manufacturer=device.get('manufacturer'),
            category=category,
            device_type=device.get('type'),
            source='local'
        )
        results[device_id] = result
        
        if result.get('from_cache'):
            cached_count += 1
        else:
            generated_count += 1
    
    print(f"Batch complete: {generated_count} generated, {cached_count} from cache")
    return results


def infer_category(device_info: dict) -> str:
    """
    Infer device category from device information.
    
    Args:
        device_info: Dictionary containing device details
        
    Returns:
        Category name string
    """
    # Keywords to category mapping
    category_keywords = {
        'Cardiovascular': ['stent', 'pacemaker', 'defibrillator', 'lvad', 'catheter', 
                          'heart', 'cardiac', 'vascular', 'coronary', 'arterial'],
        'Orthopedic': ['hip', 'knee', 'spine', 'bone', 'joint', 'orthopedic', 
                      'prosthesis', 'implant', 'fixation', 'plate', 'screw'],
        'Infusion & IV': ['infusion', 'pump', 'syringe', 'iv', 'intravenous', 
                         'injection', 'fluid', 'drip'],
        'Monitoring': ['monitor', 'sensor', 'pulse', 'oximeter', 'ecg', 'ekg', 
                      'telemetry', 'vital'],
        'Respiratory': ['ventilator', 'airway', 'respiratory', 'breathing', 
                       'oxygen', 'cpap', 'bipap', 'nebulizer'],
        'Imaging': ['imaging', 'x-ray', 'ct', 'mri', 'ultrasound', 'scanner', 
                   'diagnostic'],
        'Surgical': ['surgical', 'scalpel', 'forceps', 'retractor', 'suture', 
                    'stapler', 'instrument'],
        'Laboratory': ['lab', 'test', 'analyzer', 'reagent', 'specimen', 
                      'diagnostic'],
    }
    
    # Build searchable text from device info
    searchable = ' '.join([
        str(device_info.get('type', '')),
        str(device_info.get('description', '')),
        str(device_info.get('brand_name', '')),
        str(device_info.get('model', '')),
        str(device_info.get('gmdn_definition', ''))
    ]).lower()
    
    # Check each category's keywords
    for category, keywords in category_keywords.items():
        for keyword in keywords:
            if keyword in searchable:
                return category
    
    return 'Uncategorized'


# ============================================
# Testing / CLI Usage
# ============================================

if __name__ == "__main__":
    # Initialize database first
    from database_setup import init_db
    init_db()
    
    # Test QR code generation with caching
    test_devices = [
        {
            'id': 'test_stent_001',
            'name': 'XIENCE Alpine Stent',
            'manufacturer': 'Abbott',
            'type': 'Drug-Eluting Coronary Stent'
        },
        {
            'id': 'test_pump_001', 
            'name': 'Alaris Infusion Pump',
            'manufacturer': 'BD',
            'type': 'Infusion System'
        },
        {
            'id': 'test_hip_001',
            'name': 'Trident Hip System',
            'manufacturer': 'Stryker',
            'type': 'Hip Replacement System'
        }
    ]
    
    print("\n=== First run (should generate new QR codes) ===")
    for device in test_devices:
        result = generate_qr_code(
            device_id=device['id'],
            device_name=device['name'],
            manufacturer=device['manufacturer'],
            device_type=device['type'],
            category=infer_category({'type': device['type']}),
            source='test'
        )
        print(f"  {device['id']}: from_cache={result.get('from_cache')}")
    
    print("\n=== Second run (should use cached QR codes) ===")
    for device in test_devices:
        result = generate_qr_code(
            device_id=device['id'],
            device_name=device['name'],
            manufacturer=device['manufacturer'],
            device_type=device['type'],
            category=infer_category({'type': device['type']}),
            source='test'
        )
        print(f"  {device['id']}: from_cache={result.get('from_cache')}")
    
    print("\n=== Check existence ===")
    for device in test_devices:
        exists = qr_code_exists(device['id'])
        print(f"  {device['id']}: file={exists['file_exists']}, db={exists['db_exists']}")