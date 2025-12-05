"""
Medical Device Discovery System

A Flask application that provides:
- QR code-based device discovery
- FDA GUDID integration for device lookup
- AI-powered assistant for device questions
- Mobile-friendly web interface

STA Engineering Challenge 2026
"""

from flask import Flask, render_template, request, jsonify, send_file
import json
from pathlib import Path

from config import Config
from qr_generator import generate_qr_code, get_qr_code_path
from llm_service import ask_device_question, get_quick_questions
from gudid_service import get_device_from_gudid, parse_udi, search_devices

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)


# ============================================
# DATA LOADING
# ============================================

def load_devices() -> dict:
    """Load local device database from JSON file."""
    devices_path = Path(Config.DEVICES_FILE)
    if devices_path.exists():
        with open(devices_path) as f:
            return json.load(f)
    return {}


# Load devices at startup
DEVICES = load_devices()


# ============================================
# WEB ROUTES
# ============================================

@app.route("/")
def index():
    """Home page - shows all devices and their QR codes."""
    # Generate QR codes for all local devices
    for device_id in DEVICES.keys():
        generate_qr_code(device_id)
    
    return render_template(
        "index.html",
        devices=DEVICES,
        base_url=Config.BASE_URL,
        local_ip=Config.LOCAL_IP,
        port=Config.PORT
    )


@app.route("/device/<device_id>")
def device_page(device_id):
    """
    Device info page - what users see after scanning QR code.
    
    Looks up device in:
    1. Local database first
    2. FDA GUDID if not found locally
    3. Creates placeholder for AI assistance if not found anywhere
    """
    device = None
    source = "unknown"
    
    # First check local database
    if device_id in DEVICES:
        device = DEVICES[device_id].copy()
        device["id"] = device_id
        source = "local"
    else:
        # Try GUDID lookup
        gudid_device = get_device_from_gudid(device_id)
        if gudid_device:
            device = gudid_device
            source = "gudid"
        else:
            # Unknown device - create placeholder
            device = {
                "id": device_id,
                "manufacturer": "Unknown",
                "model": device_id.replace("_", " ").title(),
                "type": "Medical Device",
                "description": "Device not found in local database or FDA GUDID. The AI assistant will search for information.",
                "features": [],
                "common_alarms": [],
                "quick_tips": []
            }
            source = "unknown"
    
    device["source"] = source
    quick_questions = get_quick_questions(device.get("type", ""))
    
    return render_template(
        "device.html",
        device=device,
        quick_questions=quick_questions
    )


@app.route("/scan")
def scan_page():
    """Page for scanning UDI barcodes directly from devices."""
    return render_template("scan.html", base_url=Config.BASE_URL)


# ============================================
# API ROUTES
# ============================================

@app.route("/api/lookup/udi", methods=["POST"])
def lookup_by_udi():
    """
    Look up device by UDI barcode scan.
    
    Parses the UDI to extract the Device Identifier (DI),
    then looks up the device in GUDID.
    """
    data = request.get_json()
    udi = data.get("udi", "").strip()
    
    if not udi:
        return jsonify({"error": "No UDI provided"}), 400
    
    # Parse UDI to extract DI
    parsed = parse_udi(udi)
    if parsed and parsed.get("di"):
        di = parsed["di"]
        device = get_device_from_gudid(di)
        if device:
            return jsonify({
                "found": True,
                "device": device,
                "parsed_udi": parsed,
                "redirect_url": f"/device/{di}"
            })
    
    # Try direct lookup with full UDI
    device = get_device_from_gudid(udi, is_udi=True)
    if device:
        return jsonify({
            "found": True,
            "device": device,
            "redirect_url": f"/device/{device.get('id', udi)}"
        })
    
    return jsonify({
        "found": False,
        "message": "Device not found in GUDID",
        "udi": udi
    })


@app.route("/api/lookup/di/<di>")
def lookup_by_di(di):
    """Look up device by Device Identifier."""
    # Check local first
    if di in DEVICES:
        return jsonify({
            "found": True,
            "source": "local",
            "device": DEVICES[di]
        })
    
    # Try GUDID
    device = get_device_from_gudid(di)
    if device:
        return jsonify({
            "found": True,
            "source": "gudid",
            "device": device
        })
    
    return jsonify({"found": False, "message": "Device not found"}), 404


@app.route("/api/search")
def search_device():
    """Search for devices by name, manufacturer, or description."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "No search query provided"}), 400
    
    # Search local database
    local_results = []
    query_lower = query.lower()
    for device_id, device in DEVICES.items():
        searchable = f"{device.get('manufacturer', '')} {device.get('model', '')} {device.get('description', '')}".lower()
        if query_lower in searchable:
            local_results.append({**device, "id": device_id, "source": "local"})
    
    # Search GUDID
    gudid_results = []
    gudid_response = search_devices(query, limit=5)
    if gudid_response and gudid_response.get("results"):
        for result in gudid_response["results"]:
            gudid_results.append({
                "id": result.get("primaryDi", ""),
                "manufacturer": result.get("companyName", ""),
                "model": result.get("versionModelNumber", ""),
                "brand_name": result.get("brandName", ""),
                "description": result.get("deviceDescription", ""),
                "source": "gudid"
            })
    
    return jsonify({
        "query": query,
        "local_results": local_results,
        "gudid_results": gudid_results,
        "total": len(local_results) + len(gudid_results)
    })


@app.route("/api/device/<device_id>")
def get_device_info(device_id):
    """API endpoint to get device information."""
    if device_id in DEVICES:
        return jsonify({**DEVICES[device_id], "source": "local"})
    
    device = get_device_from_gudid(device_id)
    if device:
        return jsonify(device)
    
    return jsonify({"error": "Device not found"}), 404


@app.route("/api/ask", methods=["POST"])
def ask_question():
    """API endpoint to ask the AI assistant a question."""
    data = request.get_json()
    
    device_id = data.get("device_id")
    question = data.get("question")
    chat_history = data.get("chat_history", [])
    
    if not question:
        return jsonify({"error": "No question provided"}), 400
    
    # Get device info from local or GUDID
    device = DEVICES.get(device_id, {})
    if not device:
        device = get_device_from_gudid(device_id) or {}
    
    # Get AI response
    answer = ask_device_question(device, question, chat_history)
    
    return jsonify({
        "answer": answer,
        "device_id": device_id
    })


@app.route("/qr/<device_id>")
def get_qr_code(device_id):
    """Serve the QR code image for a device."""
    qr_path = get_qr_code_path(device_id)
    return send_file(qr_path, mimetype="image/png")


@app.route("/api/devices")
def list_devices():
    """List all available devices in local database."""
    return jsonify({
        device_id: {
            "manufacturer": d.get("manufacturer"),
            "model": d.get("model"),
            "type": d.get("type")
        }
        for device_id, d in DEVICES.items()
    })


@app.route("/generate-qr", methods=["POST"])
def generate_new_qr():
    """Generate a QR code for a custom device ID."""
    data = request.get_json()
    device_id = data.get("device_id")
    
    if not device_id:
        return jsonify({"error": "No device_id provided"}), 400
    
    # Sanitize device_id
    device_id = device_id.lower().replace(" ", "_")
    
    # Generate QR code
    generate_qr_code(device_id)
    
    return jsonify({
        "device_id": device_id,
        "qr_url": f"/qr/{device_id}",
        "device_url": f"{Config.BASE_URL}/device/{device_id}"
    })


# ============================================
# HEALTH CHECK
# ============================================

@app.route("/health")
def health_check():
    """Health check endpoint for Docker/monitoring."""
    return jsonify({
        "status": "healthy",
        "service": "med-device-discovery",
        "base_url": Config.BASE_URL
    })
@app.route("/api/recalls/check/<device_id>")
def check_device_recalls(device_id):
    """Check FDA openFDA API for recalls related to this device's manufacturer."""
    import requests
    
    # Get device info to find manufacturer
    device_info = get_device_from_gudid(device_id)
    if not device_info:
        device_info = DEVICES.get(device_id, {})
    
    manufacturer = device_info.get("manufacturer", "")
    
    if not manufacturer:
        return jsonify({"recalls": [], "message": "Unknown manufacturer"})
    
    try:
        # Search openFDA for recalls from this manufacturer
        search_term = manufacturer.replace(".", "").replace(",", "").split()[0]
        
        response = requests.get(
            "https://api.fda.gov/device/recall.json",
            params={
                "search": f'recalling_firm:"{search_term}"',
                "limit": 5,
                "sort": "report_date:desc"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            recalls = []
            for recall in data.get("results", []):
                recalls.append({
                    "recall_number": recall.get("res_event_number", "Unknown"),
                    "product": recall.get("product_description", "")[:150],
                    "reason": recall.get("reason_for_recall", "")[:150],
                    "firm": recall.get("recalling_firm", "Unknown"),
                    "date": recall.get("report_date", "Unknown"),
                })
            
            return jsonify({
                "manufacturer": manufacturer,
                "recalls_found": len(recalls),
                "recalls": recalls
            })
        
        return jsonify({"manufacturer": manufacturer, "recalls_found": 0, "recalls": []})
            
    except Exception as e:
        return jsonify({"error": str(e), "recalls": []}), 500

# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    print(f"""
╔════════════════════════════════════════════════════════════╗
║         MEDICAL DEVICE DISCOVERY SYSTEM                    ║
║              with FDA GUDID Integration                    ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  Server running at: http://{Config.LOCAL_IP}:{Config.PORT:<5}                  ║
║                                                            ║
║  Features:                                                 ║
║  • Scan existing UDI barcodes on devices                   ║
║  • Auto-lookup in FDA GUDID database                       ║
║  • AI-powered assistance for any device                    ║
║  • No app installation required                            ║
║                                                            ║
║  Make sure your phone is on the same WiFi network!         ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG
    )
