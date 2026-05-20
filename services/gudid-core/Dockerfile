# Build context is the REPO ROOT (see docker-compose.yml) so the image can
# bake in the fhir-bridge library modules the scan-to-chart workflow depends on.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV PORT=8090

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY services/gudid-core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY services/gudid-core/ /app/

# fhir-bridge library (GUDID -> US Core Device mapper + HAPI client)
COPY services/fhir-bridge/gudid_to_uscore_device.py services/fhir-bridge/hapi_client.py /app/

RUN mkdir -p static/qr_codes data eval/usage_logs

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 2 app:app"]
