# gudid-core

The existing Flask application (presented at STA 2026), relocated here unchanged in Phase 0.

Responsibilities:
- Query the FDA AccessGUDID API by UDI/DI (`gudid_service.py`)
- Parse UDI strings, generate QR codes (`qr_generator.py`)
- Device discovery web UI and LLM assistant (`app.py`, `llm_service.py`)

This service remains the authoritative path to **GUDID device metadata**. Other services
(`fhir-bridge`, `cds-hooks`) consume GUDID data through it; they never hardcode device data.

Run locally:

```bash
cd services/gudid-core
pip install -r requirements.txt
python app.py
```
