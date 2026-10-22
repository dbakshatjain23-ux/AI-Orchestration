"""Consent checks and append-only JSONL audit logging."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from agents.chat_protocol import build_text_uagent
from config import settings
from utils.dataset_loader import DatasetLoader


class ComplianceAuditAgent:
    def __init__(self, loader: DatasetLoader | None = None):
        self.loader = loader or DatasetLoader(
            settings.dataset_path, settings.sqlite_path, settings.parquet_path
        )
        self._audit_lock = Lock()

    def authorize_contact(self, record: Mapping[str, Any], channel: str) -> dict[str, Any]:
        channel = channel.casefold()
        allowed = self._as_bool(record.get("contact_allowed", False))
        reason = None
        age = record.get("age_at_admission")
        guardian_required = record.get("consent_status") == "guardian_required"
        if age is not None:
            try:
                guardian_required = guardian_required or int(age) < 18
            except (TypeError, ValueError):
                pass
        if guardian_required:
            allowed, reason = False, "guardian_verification_required"
        elif channel == "email" and not self._as_bool(record.get("email_consent", False)):
            allowed, reason = False, "email_consent_missing"
        elif channel == "sms" and not self._as_bool(record.get("sms_consent", False)):
            allowed, reason = False, "sms_consent_missing"
        elif not allowed:
            reason = "contact_not_allowed"
        return {
            "allowed": allowed,
            "channel": channel,
            "reason": reason,
            "patient_id": record.get("patient_id"),
        }

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        if isinstance(value, str):
            return value.strip().casefold() in {"true", "1", "yes"}
        return False

    def append_event(self, event: Mapping[str, Any], path: str | Path | None = None) -> Path:
        destination = Path(path) if path else settings.ensure_output_dir() / "audit.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(event)
        payload.setdefault("audit_event_at", datetime.now(timezone.utc).isoformat())
        line = json.dumps(payload, default=str) + "\n"
        with self._audit_lock:
            with destination.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
        return destination

    def authorize_patient(self, patient_id: str, channel: str) -> dict[str, Any]:
        rows = self.loader.exact_match("patient_id", patient_id)
        if rows.empty:
            return {"allowed": False, "patient_id": patient_id, "channel": channel, "reason": "patient_not_found"}
        record = self.loader.records(rows, limit=1)[0]
        return self.authorize_contact(record, channel)


def build_uagent():
    if settings.enable_dev4_integration:
        from services.dev4_bridge import specialist_preview
        return build_text_uagent('healthcare-compliance-audit', specialist_preview, slot=6)
    service = ComplianceAuditAgent()

    def handle(payload: Any):
        if isinstance(payload, str):
            match = re.search(r"\b(?:PAT-\d+|P\d+)\b", payload, re.IGNORECASE)
            if not match:
                return {"status": "needs_input", "message": "Include a patient ID and communication channel."}
            channel = "sms" if "sms" in payload.casefold() or "text" in payload.casefold() else "email"
            return service.authorize_patient(match.group(0), channel)
        operation = payload.get("operation", "authorize_contact")
        if operation == "authorize_contact":
            return service.authorize_contact(payload["record"], payload["channel"])
        if operation == "append_event":
            path = service.append_event(payload["event"])
            return {"status": "logged", "path": str(path)}
        raise ValueError(f"Unsupported compliance operation: {operation}")

    return build_text_uagent("healthcare-compliance-audit", handle, slot=6)


if __name__ == "__main__":  # pragma: no cover
    build_uagent().run()

