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
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    
    # OpenAI API Settings
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")  # Custom URL support
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # Default model
    
    # Server settings
    HOST = "0.0.0.0"  # Listen on all interfaces
    PORT = int(os.getenv("PORT", 5000))
    DEBUG = os.getenv("FLASK_ENV", "production") == "development"
    
    # Network settings for QR codes
    LOCAL_IP = get_local_ip()
    BASE_URL = f"http://{LOCAL_IP}:{PORT}"
    
    # File paths
    QR_CODE_DIR = "static/qr_codes"
    DEVICES_FILE = "data/devices.json"
    
    # GUDID API settings
    GUDID_BASE_URL = "https://accessgudid.nlm.nih.gov/api/v2"
    GUDID_TIMEOUT = 10  # seconds
