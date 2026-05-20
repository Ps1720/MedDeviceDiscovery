.PHONY: help up hapi down demo seed recalls test validate evaluation-report

help:
	@echo "PeriopUDI — make targets"
	@echo "  up                  Bring up the full stack (docker-compose up --build)"
	@echo "  hapi                Bring up just HAPI + Postgres and wait for it to be healthy (Phase 1)"
	@echo "  down                Stop the stack"
	@echo "  demo                Reset state and bring up the full demo stack"
	@echo "  seed                Generate Synthea patients and load them into HAPI   (Phase 1)"
	@echo "  recalls             Refresh the device-recall cache (demo + openFDA)     (Phase 5)"
	@echo "  test                Run all service test suites                          (Phase 2+)"
	@echo "  validate            Validate FHIR output against US Core v8.0.1          (Phase 2/7)"
	@echo "  evaluation-report   Run the evaluation notebook and emit a report        (Phase 8)"

up:
	docker-compose up --build

hapi:
	docker-compose up -d hapi-db hapi
	@echo "Waiting for HAPI to become healthy..."
	@until curl -sf http://localhost:8080/fhir/metadata >/dev/null 2>&1; do sleep 5; done
	@echo "HAPI ready: http://localhost:8080/fhir"

down:
	docker-compose down

demo: down
	docker-compose up --build -d
	@echo "Stack starting. gudid-core: http://localhost:5000  HAPI: http://localhost:8080/fhir"

# One-shot Synthea seeder. Requires HAPI already healthy (run `make hapi` first).
seed:
	docker-compose --profile seed run --build --rm synthea-seed
	@echo "Patient count:"
	@curl -s "http://localhost:8080/fhir/Patient?_summary=count" | head -c 400; echo

# Refresh the recall cache (seeds demo recalls + best-effort openFDA pull).
recalls:
	docker-compose exec cds-hooks python recall_poller.py
	@echo "Recall cache:"
	@curl -s "http://localhost:8091/health"; echo

test:
	@echo "Phase 2+: run pytest across services once tests exist."
	@find services -name tests -type d -exec sh -c 'echo "--- {} ---"' \;

validate:
	@echo "Phase 2/7: run services/fhir-bridge/tests/validate_against_ig.py once implemented."

evaluation-report:
	@echo "Phase 8: run eval/usability_study/analysis.ipynb once implemented."
