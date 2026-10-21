"""Deterministic EHR search specialist."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from config import settings
from agents.chat_protocol import build_text_uagent
from utils.dataset_loader import DatasetLoader


class EHRSearchAgent:
    def __init__(self, loader: DatasetLoader | None = None):
        self.loader = loader or DatasetLoader(
            settings.dataset_path, settings.sqlite_path, settings.parquet_path
        )

    def find_patient(self, name: str) -> pd.DataFrame:
        return self.loader.exact_match("patient_full_name", name)

    def find_patient_by_id(self, patient_id: str) -> pd.DataFrame:
        return self.loader.exact_match("patient_id", patient_id)

    def search(self, limit: int = 100, **criteria: Any) -> list[dict[str, Any]]:
        return self.loader.records(self.loader.filter(**criteria), limit=limit)

    def patient_summary(self, name: str) -> dict[str, Any]:
        matches = self.find_patient(name)
        if matches.empty:
            return {
                "status": "not_found",
                "message": f"No record matches patient name '{name}'.",
            }
        rows = self.loader.records(matches, limit=len(matches))
        return {"status": "ok", "count": len(rows), "records": rows}

    def handle_text(self, text: str, limit: int = 100) -> dict[str, Any]:
        """Interpret the bounded retrieval language emitted by planner agents."""

        query = text.casefold()
        patient_id = re.search(r"\b(?:pat-\d+|p\d+)\b", text, re.IGNORECASE)
        if patient_id:
            rows = self.find_patient_by_id(patient_id.group(0))
            return {"status": "ok", "count": len(rows), "records": self.loader.records(rows, limit)}

        names = self.loader.frame["patient_full_name"].dropna().astype(str).unique()
        matching_names = [name for name in names if name.casefold() in query]
        if matching_names:
            rows = self.loader.filter(patient_full_name__in=matching_names)
            return {"status": "ok", "count": len(rows), "records": self.loader.records(rows, limit)}

        criteria: dict[str, Any] = {}
        numeric_patterns = {
            "length_of_stay_days__gt": r"(?:stay|stays|length of stay).{0,24}(?:over|more than|>|longer than)\s*(\d+)",
            "age_at_admission__gt": r"(?:age|aged|patients?).{0,18}(?:over|older than|>)\s*(\d+)",
            "billing_amount_usd__gt": r"(?:bill|billing).{0,18}(?:over|more than|>)\s*\$?([\d,.]+)",
        }
        for expression, pattern in numeric_patterns.items():
            match = re.search(pattern, query)
            if match:
                criteria[expression] = float(match.group(1).replace(",", ""))
        if "abnormal" in query:
            criteria["test_result"] = "Abnormal"
        for value in self.loader.frame["gender_identity"].dropna().astype(str).unique():
            if re.search(rf"\b{re.escape(value.casefold())}\b", query):
                criteria["gender_identity"] = value
                break
        for column in ("primary_condition", "facility_name", "assigned_clinician", "payor_name"):
            for value in self.loader.frame[column].dropna().astype(str).unique():
                if value.casefold() in query:
                    criteria[column] = value
                    break
        room = re.search(r"\broom\s*(?:number\s*)?(\d+)\b", query)
        if room:
            criteria["room_number"] = int(room.group(1))
        if not criteria:
            return {
                "status": "needs_input",
                "message": "Specify a patient ID/name or supported dataset filters.",
                "supported_filters": [
                    "patient name or ID", "length of stay", "age", "billing amount",
                    "test result", "gender", "condition", "facility", "clinician", "payor", "room",
                ],
            }
        rows = self.loader.filter(**criteria)
        return {
            "status": "ok",
            "criteria": criteria,
            "count": len(rows),
            "records": self.loader.records(rows, limit),
            "truncated": len(rows) > limit,
        }


def build_uagent():
    """Build an Agent Chat Protocol wrapper when uAgents is installed."""
    service = EHRSearchAgent()

    def handle(payload: Any):
        if isinstance(payload, str):
            return service.handle_text(payload)
        operation = payload.get("operation", "search")
        if operation == "patient_summary":
            return service.patient_summary(payload["name"])
        if operation == "patient_id":
            rows = service.find_patient_by_id(payload["patient_id"])
            return {"status": "ok", "count": len(rows), "records": service.loader.records(rows)}
        if operation == "search":
            return service.search(limit=int(payload.get("limit", 100)), **payload.get("criteria", {}))
        raise ValueError(f"Unsupported EHR operation: {operation}")

    return build_text_uagent("healthcare-ehr-search", handle, slot=1)


if __name__ == "__main__":  # pragma: no cover
    build_uagent().run()

