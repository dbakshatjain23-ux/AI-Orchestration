"""Google Workspace action preparation with approval enforced at execution."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from agents.chat_protocol import build_text_uagent
from config import settings
from utils.google_client import service_account_credentials


class ApprovalRequired(PermissionError):
    pass


@dataclass(frozen=True)
class PreparedAction:
    action: str
    payload: dict[str, Any]
    status: str = "awaiting_human_approval"


class WorkspaceSyncAgent:
    def prepare_email(
        self, to: str, subject: str, body: str, patient_id: str | None = None
    ) -> PreparedAction:
        parsed = parseaddr(to)[1]
        if not parsed or "@" not in parsed or parsed != to.strip():
            raise ValueError("A single valid recipient email address is required")
        if not subject.strip() or "\n" in subject or "\r" in subject:
            raise ValueError("Email subject must be non-empty and contain no line breaks")
        if not body.strip():
            raise ValueError("Email body must be non-empty")
        payload = {"to": to, "subject": subject, "body": body}
        if patient_id:
            payload["patient_id"] = patient_id
        return PreparedAction("gmail_send", payload)

    def prepare_calendar_event(self, **payload: Any) -> PreparedAction:
        for key in ("summary", "start", "end"):
            if key not in payload:
                raise ValueError(f"Calendar event is missing {key}")
        start_value = payload["start"].get("dateTime") if isinstance(payload["start"], dict) else None
        end_value = payload["end"].get("dateTime") if isinstance(payload["end"], dict) else None
        if not start_value or not end_value:
            raise ValueError("Calendar start/end must contain dateTime")
        start = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_value.replace("Z", "+00:00"))
        if end <= start:
            raise ValueError("Calendar event end must be after start")
        return PreparedAction("calendar_create_event", payload)

    def prepare_sheet_append(
        self,
        spreadsheet_id: str,
        values: list[list[Any]],
        worksheet_name: str | None = None,
    ) -> PreparedAction:
        if not spreadsheet_id.strip():
            raise ValueError("spreadsheet_id is required")
        if not values:
            raise ValueError("At least one row is required for Sheets append")
        width = len(values[0])
        if width == 0 or any(len(row) != width for row in values):
            raise ValueError("All Sheets rows must be non-empty and have equal width")
        return PreparedAction(
            "sheets_append",
            {
                "spreadsheet_id": spreadsheet_id,
                "values": values,
                "worksheet_name": worksheet_name,
            },
        )

    def execute(self, action: PreparedAction, *, approved: bool = False) -> dict[str, Any]:
        if not approved:
            raise ApprovalRequired(f"Human approval is required for {action.action}")
        credentials = service_account_credentials(
            settings.google_service_account_file, settings.google_delegated_user
        )
        if action.action == "gmail_send":
            return self._send_email(credentials, action.payload)
        if action.action == "calendar_create_event":
            return self._create_calendar_event(credentials, action.payload)
        if action.action == "sheets_append":
            return self._append_sheet(credentials, action.payload)
        raise ValueError(f"Unsupported prepared action: {action.action}")

    @staticmethod
    def _send_email(credentials: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if not settings.google_delegated_user:
            raise RuntimeError(
                "GOOGLE_DELEGATED_USER is required for Gmail service-account sending"
            )
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install google-api-python-client for Gmail") from exc
        message = EmailMessage()
        message["To"] = payload["to"]
        message["From"] = settings.google_delegated_user
        message["Subject"] = payload["subject"]
        message.set_content(payload["body"])
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        result = (
            build("gmail", "v1", credentials=credentials, cache_discovery=False)
            .users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return {"status": "sent", "action": "gmail_send", "message_id": result.get("id")}

    @staticmethod
    def _create_calendar_event(credentials: Any, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install google-api-python-client for Calendar") from exc
        event = dict(payload)
        calendar_id = event.pop("calendar_id", "primary")
        result = (
            build("calendar", "v3", credentials=credentials, cache_discovery=False)
            .events()
            .insert(calendarId=calendar_id, body=event)
            .execute()
        )
        return {
            "status": "created",
            "action": "calendar_create_event",
            "event_id": result.get("id"),
            "html_link": result.get("htmlLink"),
        }

    @staticmethod
    def _append_sheet(credentials: Any, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            import gspread
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install gspread for Sheets sync") from exc
        spreadsheet = gspread.authorize(credentials).open_by_key(payload["spreadsheet_id"])
        worksheet_name = payload.get("worksheet_name")
        worksheet = spreadsheet.worksheet(worksheet_name) if worksheet_name else spreadsheet.sheet1
        worksheet.append_rows(payload["values"], value_input_option="USER_ENTERED")
        return {
            "status": "appended",
            "action": "sheets_append",
            "rows_appended": len(payload["values"]),
            "worksheet": worksheet.title,
        }


def build_uagent():
    if settings.enable_dev4_integration:
        from services.dev4_bridge import specialist_preview
        return build_text_uagent('healthcare-workspace-sync', specialist_preview, slot=5)
    service = WorkspaceSyncAgent()

    def handle(payload: Any):
        if not isinstance(payload, dict):
            return {
                "status": "needs_input",
                "message": "Workspace actions require structured recipients/content and are prepared only; the supervisor must approve execution.",
                "operations": ["prepare_email", "prepare_calendar_event", "prepare_sheet_append"],
            }
        operation = payload.get("operation")
        if operation == "prepare_email":
            action = service.prepare_email(
                payload["to"], payload["subject"], payload["body"], payload.get("patient_id")
            )
        elif operation == "prepare_calendar_event":
            action = service.prepare_calendar_event(**payload.get("event", {}))
        elif operation == "prepare_sheet_append":
            action = service.prepare_sheet_append(
                payload["spreadsheet_id"], payload["values"], payload.get("worksheet_name")
            )
        else:
            raise ValueError(f"Unsupported Workspace operation: {operation}")
        return {"status": action.status, "action": action.action, "payload": action.payload}

    return build_text_uagent("healthcare-workspace-sync", handle, slot=5)


if __name__ == "__main__":  # pragma: no cover
    build_uagent().run()

