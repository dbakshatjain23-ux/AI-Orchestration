"""Supervisor uAgent, ASI:One planner client, and HITL state machine."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

from agents.agent_1_ehr_search import EHRSearchAgent
from agents.agent_2_math_analytics import MathAnalyticsAgent
from agents.agent_5_workspace_sync import WorkspaceSyncAgent
from agents.agent_6_compliance_audit import ComplianceAuditAgent
from config import agent_runtime_kwargs, settings
from services.questionnaire_engine import QuestionnaireEngine
from services.workflow_orchestrator import WorkflowOrchestrator
from utils.asi_cards import approval_card, outcome_card


SUPERVISOR_SYSTEM_PROMPT = """You are CareFlow, an AI hospital-operations supervisor.
Turn the user's goal into a transparent multi-agent plan and delegate factual work to
the supplied specialist agents. Use EHR Search for records, Math & Analytics for exact
calculations, Clinical Triage only for recorded acuity/escalation fields, Document
Generator for administrative PDFs, Workspace Sync only when explicitly enabled, and
Compliance & Audit for consent and decision evidence.

Safety rules:
- Never diagnose, prescribe, or invent clinical thresholds or missing records.
- Clearly distinguish ASI:One reasoning from deterministic dataset facts.
- Prefer independent specialist calls in parallel and respect dependencies.
- If required data is missing, ask for it instead of guessing.
- Use finalize_administrative_review when the user asks for a durable abnormal-result,
  long-stay review package. It requires human approval before execution.
- Explain blocked or partial outcomes and adapt the remaining plan safely.
- Keep the final answer concise: objective, agents used, evidence, outcome, and any
  human follow-up required.
"""


CORE_ACTION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "finalize_administrative_review",
            "description": (
                "After specialist analysis, generate an audited PDF review package for "
                "patients with abnormal results and long stays. Requires human approval."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "minimum_days": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3650,
                    },
                    "max_pdf_cases": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["minimum_days", "max_pdf_cases"],
                "additionalProperties": False,
            },
        },
    }
]


EXTERNAL_ACTION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "send_gmail_outreach",
            "description": "Send patient outreach only after explicit human approval and a consent check.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string"},
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["patient_id", "to", "subject", "body"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_review",
            "description": "Create a clinician review event only after explicit human approval.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "start": {"type": "string", "description": "ISO 8601 date-time"},
                    "end": {"type": "string", "description": "ISO 8601 date-time"},
                    "attendee_email": {"type": ["string", "null"]},
                },
                "required": ["patient_id", "summary", "start", "end", "attendee_email"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_patient_queue",
            "description": "Append case rows to Google Sheets only after explicit human approval.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string"},
                    "worksheet_name": {"type": ["string", "null"]},
                    "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                },
                "required": ["spreadsheet_id", "worksheet_name", "rows"],
                "additionalProperties": False,
            },
        },
    },
]


DEV4_ACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "run_dev4_workspace_demo",
        "description": "After explicit human approval, simulate a consent-checked Sheets sync, "
        "Gmail draft, or internal calendar review using Developer 4. Never sends email or "
        "contacts Google. Use the exact record_id returned by EHR; never guess a record ID. "
        "Consent and review restrictions cannot be overridden by approval.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {"type": "string"},
                "action": {"type": "string", "enum": ["sheets_sync", "gmail_draft", "calendar_event"]},
                "start_at": {"type": "string", "description": "Timezone-aware ISO timestamp for Calendar, otherwise empty"},
                "end_at": {"type": "string", "description": "Timezone-aware ISO timestamp for Calendar, otherwise empty"},
            },
            "required": ["record_id", "action", "start_at", "end_at"],
            "additionalProperties": False,
        },
    },
}


def planner_tools() -> list[dict[str, Any]]:
    """Return safe local tools plus optional Google Workspace actions."""

    tools = list(CORE_ACTION_TOOLS)
    if settings.enable_dev4_integration:
        tools.append(DEV4_ACTION_TOOL)
    elif settings.enable_google_actions:
        tools.extend(EXTERNAL_ACTION_TOOLS)
    return tools


_DONE = object()


@dataclass
class ASIOnePlannerClient:
    api_key: str = settings.asi_one_api_key
    base_url: str = settings.asi_one_base_url
    model: str = settings.asi_one_model
    agent_addresses: tuple[str, ...] = settings.specialist_addresses
    timeout_seconds: int = 300

    def _payload(self, messages: list[dict[str, Any]], tools=None) -> dict[str, Any]:
        if not self.agent_addresses:
            raise RuntimeError(
                "Configure AGENT1_ADDRESS through AGENT6_ADDRESS before using planner mode"
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "planner_mode": True,
            "stream": True,
        }
        payload["agents"] = list(self.agent_addresses)
        if tools:
            payload["tools"] = tools
        return payload

    def _headers(self, session_id: str) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("ASI_ONE_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "x-session-id": session_id,
        }

    def stream(self, messages, session_id: str, tools=None) -> Iterator[dict[str, Any]]:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install requests to call ASI:One planner mode") from exc
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(session_id),
            json=self._payload(messages, tools),
            stream=True,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            event = self._decode_sse_line(line)
            if event is None:
                continue
            if event is _DONE:
                return
            yield event

    async def stream_async(self, messages, session_id: str, tools=None) -> AsyncIterator[dict[str, Any]]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install httpx to run the streaming supervisor") from exc
        timeout = httpx.Timeout(self.timeout_seconds, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(session_id),
                json=self._payload(messages, tools),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    event = self._decode_sse_line(line)
                    if event is None:
                        continue
                    if event is _DONE:
                        return
                    yield event

    @staticmethod
    def _decode_sse_line(line: str | bytes) -> dict[str, Any] | object | None:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line or not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if data == "[DONE]":
            return _DONE
        event = json.loads(data)
        if "error" in event:
            raise RuntimeError(f"ASI:One stream error: {event['error']}")
        return event


@dataclass
class PendingToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    raw: dict[str, Any]


@dataclass
class ConversationState:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    messages: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT}
        ]
    )
    pending_tool_calls: list[PendingToolCall] = field(default_factory=list)
    pending_assistant_message: dict[str, Any] | None = None
    last_progress: str = ""


@dataclass
class PlannerRun:
    content: str = ""
    tool_calls: list[PendingToolCall] = field(default_factory=list)
    progress_messages: list[str] = field(default_factory=list)
    session_id: str | None = None


class SupervisorService:
    """Coordinates planner sessions, specialist access, approvals, and audit."""

    def __init__(
        self,
        ehr=None,
        analytics=None,
        planner=None,
        *,
        allow_google_actions: bool | None = None,
    ) -> None:
        self.ehr = ehr or EHRSearchAgent()
        self.analytics = analytics or MathAnalyticsAgent(self.ehr.loader)
        self.questionnaire = QuestionnaireEngine(self.ehr.loader)
        self.planner = planner or ASIOnePlannerClient()
        self.workspace = WorkspaceSyncAgent()
        self.compliance = ComplianceAuditAgent(self.ehr.loader)
        self.allow_google_actions = (
            settings.enable_google_actions
            if allow_google_actions is None
            else allow_google_actions
        )
        self.sessions: dict[str, ConversationState] = {}
        self.dev4 = None
        if settings.enable_dev4_integration:
            from services.dev4_bridge import get_dev4_bridge
            self.dev4 = get_dev4_bridge()

    def handle_local(self, query: str) -> dict[str, Any]:
        """Offline verification path; production chat uses planner sessions."""
        return self.questionnaire.answer(query)

    def stream_planner(self, query: str, session_id: str | None = None):
        return self.planner.stream(
            [
                {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            session_id or str(uuid.uuid4()),
            planner_tools(),
        )

    def state_for(self, sender: str) -> ConversationState:
        return self.sessions.setdefault(sender, ConversationState())

    async def receive(self, sender: str, text: str) -> PlannerRun:
        state = self.state_for(sender)
        if state.pending_tool_calls:
            decision = self._approval_decision(text)
            if decision is None:
                names = ", ".join(call.name for call in state.pending_tool_calls)
                return PlannerRun(
                    content=f"Approval is pending for: {names}. Reply 'approve' or 'deny'.",
                    tool_calls=list(state.pending_tool_calls),
                    session_id=state.session_id,
                )
            return await self._resume_after_decision(state, approved=decision)
        state.messages.append({"role": "user", "content": text})
        return await self._run_planner(state)

    async def _run_planner(self, state: ConversationState) -> PlannerRun:
        run = PlannerRun(session_id=state.session_id)
        fragments: dict[str, dict[str, Any]] = {}
        async for event in self.planner.stream_async(
            state.messages, state.session_id, planner_tools()
        ):
            progress = self._progress_text(event)
            if progress and progress != state.last_progress:
                state.last_progress = progress
                run.progress_messages.append(progress)
            for choice in event.get("choices", []):
                delta = choice.get("delta") or choice.get("message") or {}
                if delta.get("content"):
                    run.content += delta["content"]
                for raw_call in delta.get("tool_calls") or []:
                    key = str(raw_call.get("id") or raw_call.get("index", len(fragments)))
                    current = fragments.setdefault(key, {"id": raw_call.get("id", key), "type": "function", "function": {"name": "", "arguments": ""}})
                    if raw_call.get("id"):
                        current["id"] = raw_call["id"]
                    function = raw_call.get("function") or {}
                    if function.get("name"):
                        current["function"]["name"] += function["name"]
                    arguments = function.get("arguments")
                    if isinstance(arguments, str):
                        current["function"]["arguments"] += arguments
                    elif arguments is not None:
                        current["function"]["arguments"] = arguments
        run.tool_calls = [self._parse_tool_call(raw) for raw in fragments.values()]
        if run.tool_calls:
            state.pending_tool_calls = run.tool_calls
            state.pending_assistant_message = {
                "role": "assistant",
                "content": run.content or None,
                "tool_calls": [call.raw for call in run.tool_calls],
            }
            details = "; ".join(self._describe_tool_call(call) for call in run.tool_calls)
            run.content = (
                f"Approval required before executing: {details}. "
                "Reply 'approve' to continue or 'deny' to cancel these actions."
            )
        elif run.content:
            state.messages.append({"role": "assistant", "content": run.content})
            state.messages = [state.messages[0], *state.messages[-29:]]
        return run

    async def _resume_after_decision(self, state: ConversationState, *, approved: bool) -> PlannerRun:
        if state.pending_assistant_message is None:
            raise RuntimeError("Pending tool calls have no assistant message")
        state.messages.append(state.pending_assistant_message)
        calls = list(state.pending_tool_calls)
        if approved:
            if any(call.name == "send_gmail_outreach" for call in calls):
                self.ehr.loader.frame
                self.ehr.loader._text_index("patient_id")
            semaphore = asyncio.Semaphore(
                max(1, min(settings.max_external_concurrency, len(calls)))
            )

            async def execute(call: PendingToolCall) -> dict[str, Any]:
                async with semaphore:
                    try:
                        return await asyncio.to_thread(
                            self._execute_external_tool, call, state.session_id
                        )
                    except Exception as exc:
                        result = {"status": "failed", "error": str(exc)}
                        self._audit_tool_action(
                            call, approved=True, result=result, session_id=state.session_id
                        )
                        return result

            results = await asyncio.gather(*(execute(call) for call in calls))
        else:
            results = []
            for call in calls:
                result = {"status": "denied_by_user"}
                self._audit_tool_action(
                    call, approved=False, result=result, session_id=state.session_id
                )
                results.append(result)
        for call, result in zip(calls, results):
            state.messages.append({
                "role": "tool",
                "tool_call_id": call.call_id,
                "content": json.dumps(result, default=str),
            })
        state.pending_tool_calls = []
        state.pending_assistant_message = None
        return await self._run_planner(state)

    def _execute_external_tool(
        self, call: PendingToolCall, session_id: str | None = None
    ) -> dict[str, Any]:
        arguments = call.arguments
        if self.dev4 is not None and call.name in {
            "send_gmail_outreach", "create_calendar_review", "append_patient_queue"
        }:
            result = {"status": "blocked", "reason": "legacy_google_actions_disabled_in_dev4_mode"}
        elif call.name == "run_dev4_workspace_demo":
            if self.dev4 is None:
                result = {"status": "blocked", "reason": "dev4_integration_disabled"}
            else:
                result = self.dev4.execute(arguments, session_id, call.call_id)
        elif call.name == "finalize_administrative_review":
            minimum_days = int(arguments["minimum_days"])
            max_pdf_cases = int(arguments["max_pdf_cases"])
            if not 0 <= minimum_days <= 3650:
                raise ValueError("minimum_days must be between 0 and 3650")
            if not 1 <= max_pdf_cases <= 100:
                raise ValueError("max_pdf_cases must be between 1 and 100")
            workflow = WorkflowOrchestrator(self.ehr.loader)
            package = workflow.prepare_advanced_review(
                minimum_days=minimum_days,
                spreadsheet_id=None,
                prepare_outreach=False,
                max_pdf_cases=max_pdf_cases,
            ).as_dict()
            result = {
                "status": "completed",
                "action": "finalize_administrative_review",
                "summary": package["summary"],
                "generated_files": package["generated_files"],
                "external_actions_executed": False,
            }
        elif call.name == "send_gmail_outreach":
            patient_rows = self.ehr.find_patient_by_id(arguments["patient_id"])
            if patient_rows.empty:
                result = {"status": "blocked", "reason": "patient_not_found"}
            else:
                record = self.ehr.loader.records(patient_rows, limit=1)[0]
                consent = self.compliance.authorize_contact(record, "email")
                if not consent["allowed"]:
                    result = {"status": "blocked_by_consent", "consent": consent}
                elif str(record.get("patient_email", "")).casefold() != str(arguments["to"]).casefold():
                    result = {
                        "status": "blocked",
                        "reason": "recipient_does_not_match_patient_record",
                    }
                elif not self.allow_google_actions:
                    result = {
                        "status": "blocked",
                        "reason": "google_actions_disabled",
                    }
                else:
                    action = self.workspace.prepare_email(
                        arguments["to"], arguments["subject"], arguments["body"]
                    )
                    result = self.workspace.execute(action, approved=True)
        elif call.name == "create_calendar_review":
            if not self.allow_google_actions:
                result = {"status": "blocked", "reason": "google_actions_disabled"}
                self._audit_tool_action(
                    call, approved=True, result=result, session_id=session_id
                )
                return result
            attendees = []
            if arguments.get("attendee_email"):
                attendees.append({"email": arguments["attendee_email"]})
            action = self.workspace.prepare_calendar_event(
                summary=arguments["summary"],
                start={"dateTime": arguments["start"], "timeZone": settings.time_zone},
                end={"dateTime": arguments["end"], "timeZone": settings.time_zone},
                attendees=attendees,
                description=f"Administrative review for {arguments['patient_id']}",
            )
            result = self.workspace.execute(action, approved=True)
        elif call.name == "append_patient_queue":
            if not self.allow_google_actions:
                result = {"status": "blocked", "reason": "google_actions_disabled"}
                self._audit_tool_action(
                    call, approved=True, result=result, session_id=session_id
                )
                return result
            action = self.workspace.prepare_sheet_append(
                arguments["spreadsheet_id"], arguments["rows"], arguments.get("worksheet_name")
            )
            result = self.workspace.execute(action, approved=True)
        else:
            result = {"status": "failed", "error": f"Unknown tool: {call.name}"}
        self._audit_tool_action(
            call, approved=True, result=result, session_id=session_id
        )
        return result

    def _audit_tool_action(
        self,
        call,
        *,
        approved: bool,
        result: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        self.compliance.append_event({
            "audit_event_type": "external_action_decision",
            "workflow_event_id": f"AUD-{uuid.uuid4().hex[:12].upper()}",
            "planner_session_id": session_id,
            "tool_call_id": call.call_id,
            "tool_name": call.name,
            "patient_id": call.arguments.get("patient_id"),
            "approved": approved,
            "result": result,
        })

    @staticmethod
    def _approval_decision(text: str) -> bool | None:
        stripped = text.strip()
        if stripped.startswith("@"):
            parts = stripped.split(None, 1)
            stripped = parts[1].strip() if len(parts) > 1 else stripped
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                action = str(payload.get("action", "")).casefold()
                if action in {"approve", "approved", "confirm", "proceed"}:
                    return True
                if action in {"deny", "denied", "cancel", "reject"}:
                    return False
        normalized = re.sub(r"[^a-z]+", " ", stripped.casefold()).strip()
        if normalized in {"yes", "approve", "approved", "confirm", "confirmed", "proceed"}:
            return True
        if normalized in {"no", "deny", "denied", "cancel", "reject", "rejected"}:
            return False
        words = set(normalized.split())
        if words & {"deny", "denied", "cancel", "reject", "rejected"}:
            return False
        if words & {"approve", "approved", "confirm", "confirmed", "proceed"}:
            return True
        return None

    @staticmethod
    def _parse_tool_call(raw: dict[str, Any]) -> PendingToolCall:
        function = raw.get("function") or {}
        arguments = function.get("arguments") or "{}"
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        return PendingToolCall(raw["id"], function["name"], arguments, raw)

    @staticmethod
    def _progress_text(event: dict[str, Any]) -> str | None:
        metadata = event.get("metadata") or {}
        if metadata.get("type") != "plan_state":
            return None
        status = metadata.get("plan_status", "in_progress")
        completed = total = 0
        current_description = ""
        for phase in (metadata.get("phases") or {}).values():
            for task in (phase.get("tasks") or {}).values():
                total += 1
                completed += task.get("status") == "completed"
                if task.get("status") in {"in_progress", "running"}:
                    current_description = str(
                        task.get("description") or task.get("name") or task.get("title") or ""
                    ).strip()
        detail = f" ({completed}/{total} tasks complete)" if total else ""
        if current_description:
            return f"Plan status: {status}{detail}. Current step: {current_description}"
        return f"Plan status: {status}{detail}"

    @staticmethod
    def _describe_tool_call(call: PendingToolCall) -> str:
        arguments = call.arguments
        if call.name == "run_dev4_workspace_demo":
            return (f"simulate {arguments.get('action')} for record {arguments.get('record_id')} "
                    "(mock only; consent checks still apply)")
        if call.name == "finalize_administrative_review":
            return (
                "generate an audited abnormal-result review PDF for stays longer than "
                f"{arguments.get('minimum_days')} days (up to "
                f"{arguments.get('max_pdf_cases')} detailed cases)"
            )
        if call.name == "send_gmail_outreach":
            return f"send Gmail to {arguments.get('to')} for patient {arguments.get('patient_id')}"
        if call.name == "create_calendar_review":
            return f"create calendar review '{arguments.get('summary')}' at {arguments.get('start')}"
        if call.name == "append_patient_queue":
            return (
                f"append {len(arguments.get('rows') or [])} row(s) to Google Sheet "
                f"{arguments.get('spreadsheet_id')}"
            )
        return call.name


def build_uagent():
    from uagents import Agent, Context, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement,
        ChatMessage,
        TextContent,
        chat_protocol_spec,
    )

    service = SupervisorService()
    agent = Agent(**agent_runtime_kwargs("healthcare-supervisor", 0))
    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(model=ChatAcknowledgement)
    async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(
            "Acknowledgement from %s for %s", sender, msg.acknowledged_msg_id
        )

    @protocol.on_message(model=ChatMessage)
    async def handle(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        try:
            run = await service.receive(sender, msg.text().strip())
            for progress in run.progress_messages:
                await ctx.send(sender, ChatMessage(content=[TextContent(text=progress)]))
            if run.content:
                content = [TextContent(text=run.content)]
                if settings.enable_interactive_cards:
                    if run.tool_calls:
                        content.append(approval_card(
                            [service._describe_tool_call(call) for call in run.tool_calls],
                            session_id=run.session_id,
                        ))
                    else:
                        content.append(outcome_card(
                            run.content,
                            session_id=run.session_id,
                        ))
                await ctx.send(sender, ChatMessage(content=content))
        except Exception as exc:
            ctx.logger.exception("Supervisor request failed")
            await ctx.send(sender, ChatMessage(content=[TextContent(text=f"Workflow failed: {exc}")]))

    agent.include(protocol, publish_manifest=True)
    return agent


if __name__ == "__main__":  # pragma: no cover
    build_uagent().run()
