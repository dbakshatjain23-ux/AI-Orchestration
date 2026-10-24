"""Just-in-time integration discovery for CareFlow requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IntegrationRequirement:
    key: str
    label: str
    status: str
    purpose: str
    detail: str

    @property
    def ready(self) -> bool:
        return self.status == "ready"


class IntegrationAdvisor:
    """Detect integrations explicitly needed by a user request.

    The advisor never asks users to connect unrelated services. It only reports
    dependencies for actions that the current request actually mentions.
    """

    _PATTERNS = {
        "gmail": re.compile(
            r"\b(?:gmail|outreach|notify|send (?:an? )?(?:e-?mail|message)|"
            r"draft (?:an? )?e-?mail|e-?mail (?:it|the|these|them|patients?|care team))\b",
            re.IGNORECASE,
        ),
        "calendar": re.compile(
            r"\b(?:calendar|schedule|appointment|meeting|case conference|review event)\b",
            re.IGNORECASE,
        ),
        "sheets": re.compile(
            r"\b(?:google sheets?|spreadsheet|tracking sheet|export (?:it|this|results?)|save (?:it|this|results?) to (?:a )?sheet)\b",
            re.IGNORECASE,
        ),
        "documents": re.compile(
            r"\b(?:pdf|document|report|review package|discharge summary|invoice)\b",
            re.IGNORECASE,
        ),
    }

    def __init__(self, settings: Any):
        self.settings = settings

    def requirements_for(self, text: str) -> list[IntegrationRequirement]:
        return [
            self._requirement(key)
            for key, pattern in self._PATTERNS.items()
            if pattern.search(text)
        ]

    def planner_context(self, requirements: list[IntegrationRequirement]) -> str:
        if not requirements:
            return ""
        lines = [
            "Integration readiness for this request (runtime-verified; do not contradict):"
        ]
        for item in requirements:
            lines.append(f"- {item.label}: {item.status}. {item.detail}")
        lines.append(
            "Continue safe read-only analysis when possible. Never claim that an unavailable "
            "external action was executed; instead explain what is prepared and what setup is needed."
        )
        return "\n".join(lines)

    def _requirement(self, key: str) -> IntegrationRequirement:
        if key == "documents":
            return IntegrationRequirement(
                key=key,
                label="PDF documents",
                status="ready",
                purpose="Generate a durable administrative report",
                detail="Local PDF generation is available and remains approval-gated.",
            )

        configured_file = str(self.settings.google_service_account_file).strip()
        credentials_exist = bool(configured_file) and Path(configured_file).expanduser().is_file()
        enabled = bool(self.settings.enable_google_actions)
        base_ready = configured_file and credentials_exist and enabled

        labels = {
            "gmail": "Gmail",
            "calendar": "Google Calendar",
            "sheets": "Google Sheets",
        }
        purposes = {
            "gmail": "Send consent-checked patient or care-team communication",
            "calendar": "Create a care-team review event",
            "sheets": "Append an approved operational tracking queue",
        }
        if not enabled:
            status = "setup_required"
            detail = "Google actions are disabled; analysis and drafts can still be prepared."
        elif not configured_file:
            status = "setup_required"
            detail = "A Google service-account credential file has not been configured."
        elif not credentials_exist:
            status = "setup_required"
            detail = "The configured Google credential file is not available on this runtime."
        elif key == "gmail" and not str(self.settings.google_delegated_user).strip():
            status = "setup_required"
            detail = "Gmail requires a delegated Google Workspace user before sending."
        elif base_ready:
            status = "ready"
            detail = "Connected; every write still requires explicit human approval."
        else:  # Defensive fallback for unusual settings implementations.
            status = "setup_required"
            detail = "Connection settings are incomplete."
        return IntegrationRequirement(
            key=key,
            label=labels[key],
            status=status,
            purpose=purposes[key],
            detail=detail,
        )
