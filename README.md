# Medical Device Discovery System

A QR code and AI-powered medical device discovery system for the **STA Engineering Challenge 2026**.

Anesthesiologists can scan a QR code or existing UDI barcode on any medical device with their phone camera (no app needed) to get instant device information, safety data, and AI-powered assistance.

## Features

- 📷 **Scan existing UDI barcodes** - Uses FDA GUDID database to lookup any medical device
- 🤖 **AI-powered assistant** - Ask questions about any device using Claude
- 📱 **No app required** - Works with native phone camera
- 🏥 **FDA GUDID integration** - Real manufacturer data, safety info, MRI status
- 🔍 **Custom QR codes** - Create QR codes for devices not in GUDID

---

## Quick Start with Docker (Recommended)

### Prerequisites

- Docker and Docker Compose installed
- OpenAI API key ([get one here](https://platform.openai.com/api-keys))

### 1. Clone/Download the project

```bash
cd med-device-discovery
```

### 2. Configure environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your values
nano .env  # or use any text editor
```

Fill in these values:

```bash
OPENAI_API_KEY=sk-xxxxx                 # Your OpenAI API key
HOST_IP=192.168.1.100                   # Your computer's local IP (see below)

# Optional - for custom endpoints:
OPENAI_API_BASE=https://api.openai.com/v1  # Or your custom URL
OPENAI_MODEL=gpt-4o-mini                    # Or gpt-4o, gpt-3.5-turbo, etc.
```

**Finding your local IP:**

```bash
# Mac/Linux
ifconfig | grep "inet " | grep -v 127.0.0.1

# Windows
ipconfig
# Look for "IPv4 Address"
```

### 3. Run with Docker Compose

```bash
# Build and start the container
docker-compose up --build

# Or run in background
docker-compose up -d --build
```

### 4. Access the application

Open your browser to: `http://localhost:5000`

### 5. Test with your phone

1. Ensure your phone is on the **same WiFi network**
2. Open phone camera app
3. Point at any QR code on the screen
4. Tap the notification to open the device page

---

## Docker Commands

```bash
# Start in foreground (see logs)
docker-compose up

# Start in background
docker-compose up -d

# Stop
docker-compose down

# Rebuild after code changes
docker-compose up --build

# View logs
docker-compose logs -f

# Shell into container
docker exec -it med-device-discovery /bin/bash
```

---

## Development Mode

For development with hot-reload:

```bash
docker-compose --profile dev up web-dev
```

Or run without Docker:

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run
python app.py
```

---

## Project Structure

```
med-device-discovery/
├── app.py                 # Main Flask application
├── config.py              # Configuration settings
├── gudid_service.py       # FDA GUDID API integration
├── llm_service.py         # AI assistant (OpenAI GPT)
├── qr_generator.py        # QR code generation
├── requirements.txt       # Python dependencies
├── Dockerfile             # Docker image definition
├── docker-compose.yml     # Docker Compose config
├── .env.example           # Environment template
├── data/
│   └── devices.json       # Local device database
├── templates/
│   ├── index.html         # Home page
│   ├── device.html        # Device info page
│   └── scan.html          # Barcode scanner
└── static/
    └── qr_codes/          # Generated QR code images
```

---

## How It Works

### Option A: Scan Existing Device Barcode

```
Physical Device     →    Phone Camera    →    GUDID Lookup    →    AI Help
(has UDI barcode)        (scans code)         (FDA database)       (Claude)
```

### Option B: Scan Custom QR Code

```
Custom QR Code      →    Phone Camera    →    Your Server     →    AI Help
(you create it)          (scans code)         (Flask app)          (Claude)
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Home page with QR codes |
| `/device/<id>` | GET | Device info page |
| `/scan` | GET | Barcode scanner page |
| `/api/lookup/udi` | POST | Look up by UDI |
| `/api/lookup/di/<id>` | GET | Look up by Device ID |
| `/api/search?q=` | GET | Search devices |
| `/api/ask` | POST | Ask AI assistant |
| `/qr/<id>` | GET | Get QR code image |
| `/health` | GET | Health check |

---

## Adding Custom Devices

Edit `data/devices.json`:

```json
{
    "my_device_id": {
        "manufacturer": "Acme Medical",
        "model": "Model 3000",
        "type": "Patient Monitor",
        "description": "Description here",
        "features": ["Feature 1", "Feature 2"],
        "common_alarms": [
            {
                "code": "ALARM_CODE",
                "meaning": "What it means",
                "action": "What to do"
            }
        ],
        "quick_tips": [
            "Tip 1",
            "Tip 2"
        ],
        "manual_url": "https://link-to-manual.pdf"
    }
}
```

---

## FDA GUDID Integration

This system connects to the [FDA's AccessGUDID API](https://accessgudid.nlm.nih.gov/) to retrieve:

- Manufacturer & brand name
- Device description
- MRI safety status
- Single use / sterile / latex info
- Device classification
- GMDN codes

**No API key required** - GUDID is a public database.

---

## For the Demo

1. Run the server on a laptop
2. Display QR codes on screen (or print them)
3. Attendees scan with their phones
4. Show the AI assistant answering questions

**Key talking points:**

- No app installation required
- Uses REAL FDA data (GUDID)
- AI can answer questions even for unknown devices
- Works with existing UDI barcodes

---

## Troubleshooting

### Phone can't reach the server

- Ensure phone and computer are on the same WiFi
- Check that `HOST_IP` in `.env` is correct
- Try accessing `http://YOUR_IP:5000` directly on the phone

### QR code not scanning

- Ensure good lighting
- Hold phone steady
- Try the manual entry option

### AI not responding

- Check `OPENAI_API_KEY` is set correctly
- Check API key has available credits
- If using custom URL, verify `OPENAI_API_BASE` is correct

### Docker issues

```bash
# Full rebuild
docker-compose down
docker-compose build --no-cache
docker-compose up
```

---

## License

MIT License - STA Engineering Challenge 2026

---

## Contact

For questions about the challenge specifications, contact:
**Jeff E. Mandel, MD, MS** - Chair, STA Engineering Challenge
