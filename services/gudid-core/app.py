"""
Medical Device Discovery System

A Flask application that provides:
- QR code-based device discovery
- FDA GUDID integration for device lookup
- AI-powered assistant for device questions
- Mobile-friendly web interface
- Category-based device organization

STA Engineering Challenge 2026
"""

from flask import Flask, render_template, request, jsonify, send_file
import json
from pathlib import Path

from config import Config
from database_setup import (
    create_connection, init_db, add_qr_code, get_qr_code,
    get_recent_qr_codes, get_qr_codes_by_category, get_all_categories,
    search_qr_codes, update_qr_code_category, get_stats
)
from qr_generator import generate_qr_code, get_qr_code_path, get_or_create_qr_code, infer_category
from llm_service import ask_device_question, get_quick_questions
from gudid_service import get_device_from_gudid, parse_udi, search_devices
from scan_to_chart import (
    document_device,
    list_patients,
    get_patient_chart,
    get_recent_devices,
    delete_device,
    set_implant_site,
)
import overrides as institution_overrides
import protocol_db
import protocol_seed
import protocol_service

app = Flask(__name__)
app.config.from_object(Config)


# ============================================
# DATABASE INITIALIZATION
# ============================================

# Initialize database on startup
init_db()

# Perioperative protocol knowledge base (idempotent, version-gated reseed)
protocol_db.init_db()
protocol_seed.seed_protocols()


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
    """Patient-first landing page (PeriopUDI)."""
    return render_template("home.html", base_url=Config.BASE_URL)


@app.route("/patients")
def patients_page():
    """Patient picker — choose a patient to open their device chart."""
    return render_template("patients.html")


@app.route("/api/device/<device_id>", methods=["DELETE"])
def api_delete_device(device_id):
    """Delete a documented Device from the FHIR store."""
    ok = delete_device(device_id)
    return jsonify({"success": ok, "device_id": device_id}), (200 if ok else 502)


@app.route("/api/recent-devices")
def api_recent_devices():
    """Recently documented devices across all patients (for the home feed)."""
    limit = min(request.args.get("limit", 8, type=int), 24)
    try:
        return jsonify({"devices": get_recent_devices(limit=limit)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"devices": [], "error": str(exc)}), 200


@app.route("/tools")
def tools_page():
    """Device-discovery tools (QR generator, recent/categorized devices)."""
    conn = create_connection()
    try:
        # Get recent QR codes
        recent_qr_codes = get_recent_qr_codes(conn, limit=5)
        
        # Get all categories with counts
        categories = get_all_categories(conn)
        
        # Get stats
        stats = get_stats(conn)
        
        # Get devices grouped by category
        devices_by_category = {}
        all_qr_codes = get_qr_codes_by_category(conn)
        for qr in all_qr_codes:
            cat = qr.get('category', 'Uncategorized')
            if cat not in devices_by_category:
                devices_by_category[cat] = []
            devices_by_category[cat].append(qr)
        
        return render_template(
            "index.html",
            recent_qr_codes=recent_qr_codes,
            categories=categories,
            devices_by_category=devices_by_category,
            stats=stats,
            base_url=Config.BASE_URL,
            local_ip=Config.LOCAL_IP,
            port=Config.PORT
        )
    finally:
        conn.close()


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
    
    # Ensure QR code exists in database for this device
    conn = create_connection()
    try:
        existing = get_qr_code(conn, device_id)
        if not existing:
            category = infer_category(device)
            get_or_create_qr_code(device_id, {
                'device_name': device.get('brand_name') or device.get('model'),
                'manufacturer': device.get('manufacturer'),
                'category': category,
                'type': device.get('type'),
                'source': source
            })
    finally:
        conn.close()
    
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
# SCAN-TO-CHART WORKFLOW (Phase 3 — FHIR)
# ============================================

@app.route("/scan-to-chart")
def scan_to_chart_page():
    """The hero workflow: scan a UDI and document it to a patient's chart in FHIR."""
    return render_template("scan_to_chart.html", base_url=Config.BASE_URL)


@app.route("/scan-to-chart", methods=["POST"])
def scan_to_chart_submit():
    """
    UDI -> GUDID lookup -> US Core Device -> written to the patient's chart in HAPI.
    Body: { "udi": str, "patient_id": str, "procedure_id"?: str, "user"?: str }
    """
    data = request.get_json(silent=True) or {}
    result = document_device(
        udi=(data.get("udi") or "").strip(),
        patient_id=(data.get("patient_id") or "").strip(),
        procedure_id=(data.get("procedure_id") or "").strip() or None,
        user=(data.get("user") or "demo").strip() or "demo",
        lead_config=(data.get("lead_config") or "").strip() or None,
        pocket_side=(data.get("pocket_side") or "").strip() or None,
    )
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/patients")
def api_patients():
    """Patient-picker feed sourced live from HAPI."""
    limit = min(request.args.get("limit", 50, type=int), 200)
    try:
        return jsonify({"patients": list_patients(limit=limit)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Could not reach FHIR server: {exc}"}), 502


@app.route("/patient/<patient_id>/devices")
def api_patient_devices(patient_id):
    """A patient's documented devices (newest first) plus any recall cards."""
    try:
        chart = get_patient_chart(patient_id)
        return jsonify({"patient_id": patient_id, **chart})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Could not reach FHIR server: {exc}"}), 502


@app.route("/patient/<patient_id>/timeline")
def patient_timeline_page(patient_id):
    """Rendered implant/device timeline for a patient."""
    return render_template("timeline.html", patient_id=patient_id)


# ============================================
# API ROUTES - QR CODES
# ============================================

@app.route("/generate-qr", methods=["POST"])
def generate_new_qr():
    """Generate a QR code for a device ID."""
    data = request.get_json()
    device_id = data.get("device_id", "").strip()
    
    if not device_id:
        return jsonify({"error": "No device_id provided"}), 400
    
    # Get optional device info
    device_name = data.get("device_name")
    manufacturer = data.get("manufacturer")
    category = data.get("category", "Uncategorized")
    
    # Try to get device info from GUDID if not provided
    if not device_name or not manufacturer:
        gudid_device = get_device_from_gudid(device_id)
        if gudid_device:
            device_name = device_name or gudid_device.get('brand_name') or gudid_device.get('model')
            manufacturer = manufacturer or gudid_device.get('manufacturer')
            category = infer_category(gudid_device)
    
    # Generate QR code
    result = get_or_create_qr_code(device_id, {
        'device_name': device_name,
        'manufacturer': manufacturer,
        'category': category,
        'source': 'gudid' if manufacturer else 'manual'
    })
    
    return jsonify({
        "device_id": result.get('device_id'),
        "qr_url": result.get('qr_url'),
        "device_url": result.get('device_url'),
        "device_name": result.get('device_name'),
        "manufacturer": result.get('manufacturer'),
        "category": result.get('category'),
        "from_db": result.get('from_db', False)
    })


@app.route("/qr/<device_id>")
def get_qr_code_image(device_id):
    """Serve the QR code image for a device."""
    qr_path = get_qr_code_path(device_id)
    return send_file(qr_path, mimetype="image/png")


@app.route("/api/qr/recent")
def get_recent_qr_api():
    """Get recently generated QR codes."""
    limit = request.args.get("limit", 5, type=int)
    limit = min(limit, 20)  # Cap at 20
    
    conn = create_connection()
    try:
        recent = get_recent_qr_codes(conn, limit=limit)
        return jsonify({"qr_codes": recent, "count": len(recent)})
    finally:
        conn.close()


@app.route("/api/qr/category/<category>")
def get_qr_by_category(category):
    """Get QR codes by category."""
    conn = create_connection()
    try:
        qr_codes = get_qr_codes_by_category(conn, category)
        return jsonify({"category": category, "qr_codes": qr_codes, "count": len(qr_codes)})
    finally:
        conn.close()


@app.route("/api/qr/<device_id>/category", methods=["PUT"])
def update_qr_category(device_id):
    """Update the category of a QR code."""
    data = request.get_json()
    new_category = data.get("category")
    
    if not new_category:
        return jsonify({"error": "No category provided"}), 400
    
    conn = create_connection()
    try:
        success = update_qr_code_category(conn, device_id, new_category)
        if success:
            return jsonify({"success": True, "device_id": device_id, "category": new_category})
        return jsonify({"error": "QR code not found"}), 404
    finally:
        conn.close()


@app.route("/api/categories")
def get_categories_api():
    """Get all categories with device counts."""
    conn = create_connection()
    try:
        categories = get_all_categories(conn)
        return jsonify({"categories": categories})
    finally:
        conn.close()


@app.route("/api/stats")
def get_stats_api():
    """Get database statistics."""
    conn = create_connection()
    try:
        stats = get_stats(conn)
        return jsonify(stats)
    finally:
        conn.close()


# ============================================
# API ROUTES - DEVICE LOOKUP
# ============================================

@app.route("/api/lookup/udi", methods=["POST"])
def lookup_by_udi():
    """
    Look up device by UDI barcode scan.
    """
    data = request.get_json()
    udi = data.get("udi", "").strip()
    context = (data.get("context") or "").strip() or protocol_service.DEFAULT_CONTEXT

    if not udi:
        return jsonify({"error": "No UDI provided"}), 400

    # A pure-numeric string is a bare Device Identifier (same rule as the
    # scan-to-chart workflow's _resolve_di) — look it up directly.
    if udi.isdigit():
        device = get_device_from_gudid(udi)
        if device:
            return jsonify({
                "found": True,
                "device": device,
                "protocol": _safe_protocol(device, context),
                "redirect_url": f"/device/{udi}"
            })

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
                "protocol": _safe_protocol(device, context),
                "redirect_url": f"/device/{di}"
            })

    # Try direct lookup with full UDI
    device = get_device_from_gudid(udi, is_udi=True)
    if device:
        return jsonify({
            "found": True,
            "device": device,
            "protocol": _safe_protocol(device, context),
            "redirect_url": f"/device/{device.get('id', udi)}"
        })

    return jsonify({
        "found": False,
        "message": "Device not found in GUDID",
        "udi": udi
    })


def _safe_protocol(record, context):
    """Protocol enrichment is advisory — never let it break a lookup."""
    try:
        return protocol_service.build_protocol_block(record, context)
    except Exception as exc:  # noqa: BLE001
        print(f"[protocol] failed to build protocol block: {exc}")
        return None


# ============================================
# PERIOPERATIVE PROTOCOL LAYER
# ============================================

@app.route("/api/protocol/by-di/<di>")
def api_protocol_by_di(di):
    """
    Perioperative protocol block for a device identifier (timeline expander
    and context switching). GUDID lookups are TTL-cached in-process.
    """
    context = request.args.get("context", protocol_service.DEFAULT_CONTEXT)
    if context not in protocol_db.CONTEXTS:
        return jsonify({"error": f"context must be one of {list(protocol_db.CONTEXTS)}"}), 400
    try:
        protocol = protocol_service.build_protocol_for_di(di, context)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"found": False, "error": str(exc)}), 502
    if protocol is None:
        return jsonify({"found": False, "device_identifier": di})
    return jsonify({"found": True, "device_identifier": di, "protocol": protocol})


@app.route("/api/device/<device_id>/implant-site", methods=["PUT"])
def api_set_implant_site(device_id):
    """
    Set the clinician-confirmed implant location on a documented Device.
    Body: { "lead_config": str, "pocket_side"?: str }
    """
    data = request.get_json(silent=True) or {}
    lead_config = (data.get("lead_config") or "").strip()
    if not lead_config:
        return jsonify({"success": False, "error": "lead_config is required"}), 400
    result = set_implant_site(
        device_id,
        lead_config,
        (data.get("pocket_side") or "").strip() or None,
    )
    if result.get("success"):
        return jsonify(result)
    error = result.get("error") or ""
    status = 400 if ("not valid" in error or "not a covered" in error) else 502
    return jsonify(result), status


@app.route("/admin/overrides")
def admin_overrides_page():
    """Read-only view of institutional overrides (edited via the JSON file)."""
    return render_template("admin_overrides.html")


@app.route("/api/admin/overrides")
def api_admin_overrides():
    """Active institutional overrides plus any parse errors — read-only."""
    data = institution_overrides.load_overrides()
    return jsonify({
        "institution": data["institution"],
        "file": str(institution_overrides.OVERRIDES_PATH),
        "overrides": institution_overrides.list_overrides(),
        "errors": data["errors"],
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
    
    conn = create_connection()
    try:
        # First search our local QR code database
        db_results = search_qr_codes(conn, query)
        
        # Search local devices JSON
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
            "db_results": db_results,  # QR codes already in our database
            "local_results": local_results,  # From devices.json
            "gudid_results": gudid_results,  # From FDA GUDID
            "total": len(db_results) + len(local_results) + len(gudid_results)
        })
    finally:
        conn.close()


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
# HEALTH CHECK
# ============================================

@app.route("/health")
def health_check():
    """Health check endpoint for Docker/monitoring."""
    conn = create_connection()
    try:
        stats = get_stats(conn)
        return jsonify({
            "status": "healthy",
            "service": "med-device-discovery",
            "base_url": Config.BASE_URL,
            "stats": stats
        })
    finally:
        conn.close()


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
║  • Category-based device organization                      ║
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