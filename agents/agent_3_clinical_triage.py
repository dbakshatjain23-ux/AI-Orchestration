"""Dataset-defined administrative triage rules.

This module reports recorded acuity and escalation fields. It does not diagnose
patients or invent clinical thresholds.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from agents.chat_protocol import build_text_uagent
from config import settings
from utils.dataset_loader import DatasetLoader


class ClinicalTriageAgent:
    def __init__(self, loader: DatasetLoader | None = None):
        self.loader = loader or DatasetLoader(
            settings.dataset_path, settings.sqlite_path, settings.parquet_path
        )

    def assess(self, record: Mapping[str, Any]) -> dict[str, Any]:
        required = ("acuity_score", "human_review_required", "escalation_required")
        missing = [name for name in required if name not in record]
        if missing:
            raise ValueError("Missing triage fields: " + ", ".join(missing))
        return {
            "acuity_score": int(record["acuity_score"]),
            "clinical_priority": record.get("clinical_priority"),
            "human_review_required": self._as_bool(record["human_review_required"]),
            "human_review_reason": record.get("human_review_reason"),
            "escalation_required": self._as_bool(record["escalation_required"]),
            "escalation_level": record.get("escalation_level"),
            "escalation_owner_role": record.get("escalation_owner_role"),
            "source": "recorded_dataset_fields",
        }

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        return isinstance(value, str) and value.strip().casefold() in {"true", "1", "yes"}

    def assess_patient(self, patient_id: str) -> dict[str, Any]:
        rows = self.loader.exact_match("patient_id", patient_id)
        if rows.empty:
            return {"status": "not_found", "patient_id": patient_id}
        assessments = [self.assess(row) for row in self.loader.records(rows, limit=100)]
        return {"status": "ok", "patient_id": patient_id, "assessments": assessments}


def build_uagent():
    service = ClinicalTriageAgent()

    def handle(payload: Any):
        if isinstance(payload, str):
            match = re.search(r"\b(?:PAT-\d+|P\d+)\b", payload, re.IGNORECASE)
            if not match:
                return {"status": "needs_input", "message": "Include a patient ID or a structured encounter record."}
            return service.assess_patient(match.group(0))
        return service.assess(payload.get("record", payload))

    return build_text_uagent("healthcare-clinical-triage", handle, slot=3)


if __name__ == "__main__":  # pragma: no cover
    build_uagent().run()

