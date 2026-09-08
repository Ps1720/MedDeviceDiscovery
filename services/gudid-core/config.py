import os
import socket
from dotenv import load_dotenv

load_dotenv()


def get_local_ip():
    """
    Get the local IP address of this machine.
    In Docker, use HOST_IP environment variable.
    """
    # First check if HOST_IP is set (required for Docker)
    host_ip = os.getenv("HOST_IP")
    if host_ip and host_ip != "your_local_ip_here":
        return host_ip
    
    # Try to auto-detect local IP (works when running locally, not in Docker)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


class Config:
    """Flask application configuration."""
    
    # Security
    # Signs the Flask session cookie. A stable value is REQUIRED for SMART App
    # Launch — the OAuth2 state / PKCE verifier / access token live in the
    # session across the authorize redirect.
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # ---- SMART App Launch v2 (services/gudid-core/smart_launch.py) ----
    # Public client, PKCE, no secret. Tested against the SMART Health IT
    # sandbox launcher (https://launch.smarthealthit.org).
    SMART_CLIENT_ID = os.getenv("SMART_CLIENT_ID", "periop-udi")
    SMART_SCOPES = os.getenv(
        "SMART_SCOPES",
        "launch openid fhirUser profile "
        "patient/Patient.read patient/Device.read patient/Device.write "
        "patient/Procedure.read",
    )
    # Scopes for a standalone launch (no EHR "launch" param): swap the EHR
    # "launch" scope for "launch/patient" so the auth server shows a patient picker.
    SMART_STANDALONE_SCOPES = os.getenv(
        "SMART_STANDALONE_SCOPES",
        "launch/patient openid fhirUser profile "
        "patient/Patient.read patient/Device.read patient/Device.write "
        "patient/Procedure.read",
    )
    # FHIR base used for a standalone launch (the EHR supplies its own on an EHR launch).
    SMART_DEFAULT_ISS = os.getenv(
        "SMART_DEFAULT_ISS", "https://launch.smarthealthit.org/v/r4/fhir"
    )
    # Public base URL of THIS app, for building the OAuth redirect_uri.
    APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")

    
    # OpenAI API Settings
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")  # Custom URL support
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # Default model
    
    # Server settings
    HOST = "0.0.0.0"  # Listen on all interfaces
    PORT = int(os.getenv("PORT", 8080))
    DEBUG = os.getenv("FLASK_ENV", "production") == "development"
    
    # Network settings for QR codes
    LOCAL_IP = get_local_ip()
    BASE_URL = f"http://{LOCAL_IP}:{PORT}"
    
    # File paths
    QR_CODE_DIR = "static/qr_codes"
    DEVICES_FILE = "data/devices.json"
    
    # GUDID API settings (FIXED: v2 -> v3)
    GUDID_BASE_URL = "https://accessgudid.nlm.nih.gov/api/v3"
    GUDID_TIMEOUT = 10  # seconds