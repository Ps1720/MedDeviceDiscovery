"""
Thin FHIR REST client for the local HAPI server.

HAPI is the source of truth for patient/device state; all device reads and
writes go through here.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import requests

DEFAULT_BASE_URL = os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir")
_JSON = "application/fhir+json"


class FhirError(RuntimeError):
    """Raised when HAPI returns a non-success response."""

    def __init__(self, message: str, *, status: int, outcome: Any = None):
        super().__init__(message)
        self.status = status
        self.outcome = outcome


class HapiClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 30,
        extra_headers: Optional[dict] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": _JSON})
        # Used to carry a SMART App Launch bearer token when the app is running
        # inside an EHR-launched session (see services/gudid-core/smart_launch.py).
        if extra_headers:
            self.session.headers.update(extra_headers)

    # ---- writes ----

    def create_device(self, device_resource: dict) -> str:
        """Create a Device and return its server-assigned logical id."""
        resp = self.session.post(
            f"{self.base_url}/Device",
            json=device_resource,
            headers={"Content-Type": _JSON},
            timeout=self.timeout,
        )
        self._raise_for_status(resp, "create Device")
        return resp.json()["id"]

    def update_device(self, device_resource: dict) -> dict:
        """Update an existing Device (requires resource['id']); returns the stored resource."""
        device_id = device_resource.get("id")
        if not device_id:
            raise FhirError("update_device requires resource['id']", status=0)
        resp = self.session.put(
            f"{self.base_url}/Device/{device_id}",
            json=device_resource,
            headers={"Content-Type": _JSON},
            timeout=self.timeout,
        )
        self._raise_for_status(resp, "update Device")
        return resp.json()

    def link_to_procedure(self, device_id: str, procedure_id: str) -> None:
        """Add the Device to Procedure.focalDevice via a JSON Patch."""
        patch = [
            {
                "op": "add",
                "path": "/focalDevice",
                "value": [{"manipulated": {"reference": f"Device/{device_id}"}}],
            }
        ]
        resp = self.session.patch(
            f"{self.base_url}/Procedure/{procedure_id}",
            json=patch,
            headers={"Content-Type": "application/json-patch+json"},
            timeout=self.timeout,
        )
        self._raise_for_status(resp, "link Device to Procedure")

    # ---- reads ----

    def get_device(self, device_id: str) -> dict:
        """Fetch a single Device resource by logical id."""
        resp = self.session.get(
            f"{self.base_url}/Device/{device_id}",
            timeout=self.timeout,
        )
        self._raise_for_status(resp, "read Device")
        return resp.json()

    def get_patient_devices(self, patient_id: str) -> list[dict]:
        """Return all Device resources whose patient is Patient/<patient_id>."""
        resp = self.session.get(
            f"{self.base_url}/Device",
            params={"patient": f"Patient/{patient_id}"},
            timeout=self.timeout,
        )
        self._raise_for_status(resp, "search Devices by patient")
        bundle = resp.json()
        return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]

    # ---- validation ----

    def validate(self, resource: dict, profile: Optional[str] = None) -> dict:
        """
        Validate a resource via the server's $validate operation against the
        IGs loaded into HAPI (US Core v8.0.1). Returns the OperationOutcome.
        """
        params = {"profile": profile} if profile else None
        resp = self.session.post(
            f"{self.base_url}/{resource['resourceType']}/$validate",
            json=resource,
            headers={"Content-Type": _JSON},
            params=params,
            timeout=self.timeout,
        )
        # $validate returns 200 even when issues exist; the OperationOutcome carries them.
        return resp.json()

    @staticmethod
    def outcome_errors(outcome: dict) -> list[str]:
        """Extract error/fatal diagnostics from an OperationOutcome."""
        errors = []
        for issue in outcome.get("issue", []):
            if issue.get("severity") in ("error", "fatal"):
                errors.append(
                    issue.get("diagnostics")
                    or issue.get("details", {}).get("text")
                    or issue.get("code", "unknown error")
                )
        return errors

    def _raise_for_status(self, resp: requests.Response, action: str) -> None:
        if resp.status_code >= 300:
            outcome = None
            try:
                outcome = resp.json()
            except ValueError:
                pass
            detail = ""
            if isinstance(outcome, dict) and outcome.get("resourceType") == "OperationOutcome":
                detail = "; ".join(self.outcome_errors(outcome)) or str(outcome)
            raise FhirError(
                f"Failed to {action}: HTTP {resp.status_code} {detail}",
                status=resp.status_code,
                outcome=outcome,
            )
