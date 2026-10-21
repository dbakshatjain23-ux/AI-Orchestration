"""Google Workspace clients with explicit credential and delegation checks."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
)


def service_account_credentials(
    credential_file: str, delegated_user: str = "", scopes: Iterable[str] = SCOPES
):
    if not credential_file:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is not configured")
    path = Path(credential_file)
    if not path.exists():
        raise FileNotFoundError(f"Google credential file not found: {path}")
    try:
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install google-auth for Workspace integration") from exc
    credentials = service_account.Credentials.from_service_account_file(
        str(path), scopes=list(scopes)
    )
    return credentials.with_subject(delegated_user) if delegated_user else credentials

