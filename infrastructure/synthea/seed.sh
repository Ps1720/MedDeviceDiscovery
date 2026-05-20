#!/usr/bin/env bash
# Generate Synthea synthetic patients and load them into HAPI.
# Synthetic data only — never real PHI (Build.md §7).
set -euo pipefail

FHIR_BASE_URL="${FHIR_BASE_URL:-http://hapi:8080/fhir}"
PATIENT_COUNT="${PATIENT_COUNT:-50}"
WORK="/synthea-work"
JAR="$WORK/synthea-with-dependencies.jar"
OUT="$WORK/output"
SYNTHEA_URL="https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar"

echo "[seed] FHIR base: $FHIR_BASE_URL   patients: $PATIENT_COUNT"

echo "[seed] waiting for HAPI to respond at $FHIR_BASE_URL/metadata ..."
for i in $(seq 1 60); do
  if curl -sf "$FHIR_BASE_URL/metadata" >/dev/null 2>&1; then
    echo "[seed] HAPI is reachable."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "[seed] ERROR: HAPI not reachable after 5 minutes" >&2
    exit 1
  fi
  sleep 5
done

if [ ! -f "$JAR" ]; then
  echo "[seed] downloading Synthea (cached in $WORK for reuse)..."
  curl -fL -o "$JAR" "$SYNTHEA_URL"
fi

rm -rf "$OUT"
echo "[seed] generating $PATIENT_COUNT patients (with perioperative_surgery module)..."
java -jar "$JAR" \
  -p "$PATIENT_COUNT" \
  -d "$WORK/modules" \
  --exporter.baseDirectory "$OUT" \
  --exporter.fhir.transaction_bundle true \
  --exporter.fhir.use_us_core_ig false \
  --exporter.hospital.fhir.export true \
  --exporter.practitioner.fhir.export true \
  --exporter.csv.export false

FHIR_DIR="$OUT/fhir"
if [ ! -d "$FHIR_DIR" ]; then
  echo "[seed] ERROR: no FHIR output at $FHIR_DIR" >&2
  exit 1
fi

post_bundle() {
  local f="$1" code
  code=$(curl -s -o /tmp/resp.json -w "%{http_code}" \
    -H "Content-Type: application/fhir+json" \
    -X POST "$FHIR_BASE_URL" --data-binary @"$f")
  echo "[seed] POST $(basename "$f") -> HTTP $code"
  if [ "$code" -ge 300 ]; then
    echo "[seed]   response:"; head -c 600 /tmp/resp.json; echo
  fi
}

# Organizations/Practitioners are referenced by patient bundles — load them first.
for f in "$FHIR_DIR"/hospitalInformation*.json; do [ -e "$f" ] && post_bundle "$f"; done
for f in "$FHIR_DIR"/practitionerInformation*.json; do [ -e "$f" ] && post_bundle "$f"; done

# Then the per-patient transaction bundles.
for f in "$FHIR_DIR"/*.json; do
  case "$(basename "$f")" in
    hospitalInformation*|practitionerInformation*) continue ;;
  esac
  post_bundle "$f"
done

echo "[seed] done. Verify: curl \"$FHIR_BASE_URL/Patient?_summary=count\""
