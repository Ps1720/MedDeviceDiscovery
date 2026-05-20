.PHONY: help up down demo seed test validate evaluation-report

help:
	@echo "PeriopUDI — make targets"
	@echo "  up                  Bring up the stack (docker-compose up --build)"
	@echo "  down                Stop the stack"
	@echo "  demo                Reset state and bring up the full demo stack"
	@echo "  seed                Generate Synthea patients and load them into HAPI   (Phase 1)"
	@echo "  test                Run all service test suites                          (Phase 2+)"
	@echo "  validate            Validate FHIR output against US Core v8.0.1          (Phase 2/7)"
	@echo "  evaluation-report   Run the evaluation notebook and emit a report        (Phase 8)"

up:
	docker-compose up --build

down:
	docker-compose down

demo: down
	docker-compose up --build -d
	@echo "Stack starting. gudid-core: http://localhost:$${PORT:-8080}  HAPI: http://localhost:8080/fhir (Phase 1)"

seed:
	@echo "Phase 1: implement infrastructure/synthea/seed.sh, then wire this target."
	@test -x infrastructure/synthea/seed.sh && infrastructure/synthea/seed.sh || true

test:
	@echo "Phase 2+: run pytest across services once tests exist."
	@find services -name tests -type d -exec sh -c 'echo "--- {} ---"' \;

validate:
	@echo "Phase 2/7: run services/fhir-bridge/tests/validate_against_ig.py once implemented."

evaluation-report:
	@echo "Phase 8: run eval/usability_study/analysis.ipynb once implemented."
