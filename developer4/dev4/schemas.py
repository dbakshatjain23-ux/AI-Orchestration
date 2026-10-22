from typing import Literal
from uagents import Model
from pydantic.v1 import Field

Action = Literal['sheets_sync', 'gmail_draft', 'calendar_event']

class WorkspaceRequest(Model):
    request_id: str = Field(min_length=1, max_length=100)
    record_id: str = Field(min_length=1, max_length=100)
    action: Action
    start_at: str = ''
    end_at: str = ''

class WorkspaceResponse(Model):
    request_id: str
    status: str
    reasons: list[str] = Field(default_factory=list)
    resource_id: str = ''

class ComplianceRequest(Model):
    request_id: str
    record_id: str
    action: Action

class ComplianceResponse(Model):
    request_id: str
    allowed: bool
    reasons: list[str]

