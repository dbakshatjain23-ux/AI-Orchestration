"""Supervisor uAgent, ASI:One planner client, and HITL state machine."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Any, AsyncIterator, Iterator

from agents.agent_1_ehr_search import EHRSearchAgent
from agents.agent_2_math_analytics import MathAnalyticsAgent
from agents.agent_5_workspace_sync import WorkspaceSyncAgent
from agents.agent_6_compliance_audit import ComplianceAuditAgent
from config import agent_runtime_kwargs, settings
from services.integration_advisor import IntegrationAdvisor, IntegrationRequirement
from services.questionnaire_engine import QuestionnaireEngine
from services.workflow_orchestrator import WorkflowOrchestrator
from utils.asi_cards import approval_card, workflow_result_card


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
- Treat integration readiness supplied with the user request as authoritative. Prepare
  safe drafts when execution is unavailable, but never claim that a disconnected
  service was used.
- In the final answer, state the filters and record counts that were actually used so
  deterministic results can be reconciled.
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


def planner_tools(request_text: str = "") -> list[dict[str, Any]]:
    """Expose only actions the user explicitly requested in this turn."""

    query = request_text.casefold()
    tools: list[dict[str, Any]] = []
    wants_document = (
        any(verb in query for verb in ("generate", "create", "prepare", "export"))
        and any(noun in query for noun in ("pdf", "report", "review package", "document"))
    )
    if wants_document:
        tools.extend(CORE_ACTION_TOOLS)
    if settings.enable_google_actions:
        requested_names: set[str] = set()
        if any(term in query for term in ("gmail", "email", "send mail", "outreach")):
            requested_names.add("send_gmail_outreach")
        if any(term in query for term in ("calendar", "schedule", "appointment")):
            requested_names.add("create_calendar_review")
        if any(term in query for term in ("google sheet", "spreadsheet", "save to sheets")):
            requested_names.add("append_patient_queue")
        tools.extend(
            tool for tool in EXTERNAL_ACTION_TOOLS
            if tool["function"]["name"] in requested_names
        )
    return tools


_DONE = object()


class IncompletePlannerStreamError(RuntimeError):
    """ASI:One closed a streamed planner response before its DONE sentinel."""


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
        emitted_terminal_data = False
        for attempt in range(2):
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(session_id),
                json=self._payload(messages, tools),
                stream=True,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            saw_done = False
            for line in response.iter_lines(decode_unicode=True):
                event = self._decode_sse_line(line)
                if event is None:
                    continue
                if event is _DONE:
                    saw_done = True
                    break
                emitted_terminal_data = (
                    emitted_terminal_data or self._has_terminal_delta(event)
                )
                yield event
            if saw_done:
                return
            if attempt == 0 and not emitted_terminal_data:
                continue
            raise IncompletePlannerStreamError(
                "ASI:One planner stream closed before the completion marker"
            )

    async def stream_async(self, messages, session_id: str, tools=None) -> AsyncIterator[dict[str, Any]]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install httpx to run the streaming supervisor") from exc
        timeout = httpx.Timeout(self.timeout_seconds, connect=30.0)
        emitted_terminal_data = False
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(2):
                saw_done = False
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
                            saw_done = True
                            break
                        emitted_terminal_data = (
                            emitted_terminal_data or self._has_terminal_delta(event)
                        )
                        yield event
                if saw_done:
                    return
                if attempt == 0 and not emitted_terminal_data:
                    await asyncio.sleep(0.25)
                    continue
                raise IncompletePlannerStreamError(
                    "ASI:One planner stream closed before the completion marker"
                )

    @staticmethod
    def _has_terminal_delta(event: dict[str, Any]) -> bool:
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            if delta.get("content") or delta.get("tool_calls"):
                return True
        return False

    @staticmethod
    def _decode_sse_line(line: str | bytes) -> dict[str, Any] | object | None:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line or not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if data == "[DONE]":
            return _DONE
        # ASI:One may interleave keepalive/status markers with JSON SSE events.
        # They are transport metadata, not planner output, so ignore them rather
        # than failing the entire user request.
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict):
            return None
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
    last_user_query: str = ""
    last_result: str = ""


@dataclass
class PlannerRun:
    content: str = ""
    tool_calls: list[PendingToolCall] = field(default_factory=list)
    progress_messages: list[str] = field(default_factory=list)
    integrations: list[IntegrationRequirement] = field(default_factory=list)
    execution_results: list[dict[str, Any]] = field(default_factory=list)
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
        self.integration_advisor = IntegrationAdvisor(settings)
        self.allow_google_actions = (
            settings.enable_google_actions
            if allow_google_actions is None
            else allow_google_actions
        )
        self.sessions: dict[str, ConversationState] = {}

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
            planner_tools(query),
        )

    def state_for(self, sender: str) -> ConversationState:
        return self.sessions.setdefault(sender, ConversationState())

    async def receive(
        self,
        sender: str,
        text: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> PlannerRun:
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
            return await self._resume_after_decision(
                state, approved=decision, on_progress=on_progress
            )

        selection = self._card_selection(text)
        if selection:
            local = self._handle_card_action(state, selection)
            if isinstance(local, PlannerRun):
                return local
            if local:
                text = local

        requirements = self.integration_advisor.requirements_for(text)
        state.last_user_query = text
        if self.analytics.is_operational_analysis_request(text):
            result = await asyncio.to_thread(self.analytics.operational_analysis)
            content = self.analytics.format_operational_analysis(result)
            activity = [
                f"Math Analytics filtered {result['billing']['record_count']:,} billing records above $10,000.",
                "Math Analytics calculated payor and facility billing groups in one pass.",
                "Math Analytics compared facility LOS using record counts, confidence intervals, and a practical-effect threshold.",
                f"Math Analytics tested condition + admission-type billing groups; {result['billing_anomalies']['record_count']:,} records met the anomaly rule.",
            ]
            state.last_result = content
            state.messages.append({"role": "user", "content": text})
            state.messages.append({"role": "assistant", "content": content})
            state.messages = [state.messages[0], *state.messages[-29:]]
            return PlannerRun(
                content=content,
                progress_messages=activity,
                integrations=requirements,
                session_id=state.session_id,
            )
        planner_context = self.integration_advisor.planner_context(requirements)
        planner_text = f"{text}\n\n{planner_context}" if planner_context else text
        state.messages.append({"role": "user", "content": planner_text})
        run = await self._run_planner(
            state,
            tools=planner_tools(text),
            on_progress=on_progress,
        )
        run.integrations = requirements
        if run.content and not run.tool_calls:
            state.last_result = run.content
        return run

    async def _run_planner(
        self,
        state: ConversationState,
        *,
        tools: list[dict[str, Any]] | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> PlannerRun:
        run = PlannerRun(session_id=state.session_id)
        fragments: dict[str, dict[str, Any]] = {}
        async for event in self.planner.stream_async(
            state.messages, state.session_id, tools or None
        ):
            progress = self._progress_text(event)
            if progress and progress != state.last_progress:
                state.last_progress = progress
                run.progress_messages.append(progress)
                if on_progress is not None:
                    await on_progress(progress)
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
        if not run.content and not run.tool_calls:
            raise RuntimeError(
                "ASI:One planner ended without a final answer or actionable tool call"
            )
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

    async def _resume_after_decision(
        self,
        state: ConversationState,
        *,
        approved: bool,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> PlannerRun:
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
        # The approved/denied action has already been resolved. Do not expose
        # the same tool again or the planner can request an approval loop.
        run = await self._run_planner(state, tools=[], on_progress=on_progress)
        run.execution_results = results
        if run.content:
            state.last_result = run.content
        return run

    @staticmethod
    def _card_selection(text: str) -> dict[str, Any] | None:
        """Extract a direct card selection while tolerating an @mention prefix."""

        candidate = text.strip()
        brace = candidate.find("{")
        if brace < 0:
            return None
        try:
            payload = json.loads(candidate[brace:])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) and payload.get("action") else None

    def _handle_card_action(
        self, state: ConversationState, selection: dict[str, Any]
    ) -> str | PlannerRun | None:
        action = str(selection.get("action", "")).casefold()
        previous = state.last_user_query or "the previous CareFlow result"
        if action == "generate_pdf_report":
            return (
                "Generate an administrative PDF report for the previous result. "
                f"Preserve the filters and evidence from this objective: {previous}"
            )
        if action == "save_to_google_sheets":
            requirements = self.integration_advisor.requirements_for(
                "Save the previous result to Google Sheets"
            )
            if not all(item.ready for item in requirements):
                return PlannerRun(
                    content=(
                        "Google Sheets is not connected on this runtime yet. The result "
                        "is unchanged and no write was attempted. Configure the service "
                        "account and enable Google actions, then choose Save to Sheets again."
                    ),
                    progress_messages=[
                        "Integration check completed; Google Sheets setup is required."
                    ],
                    integrations=requirements,
                    session_id=state.session_id,
                )
            return (
                "Save the previous result to Google Sheets. Ask me for the target "
                "spreadsheet ID and worksheet name before preparing any write."
            )
        if action == "schedule_review":
            requirements = self.integration_advisor.requirements_for(
                "Schedule a review in Google Calendar"
            )
            if not all(item.ready for item in requirements):
                return PlannerRun(
                    content=(
                        "Google Calendar is not connected on this runtime yet. No event "
                        "was created. Configure the Google connection and enable actions "
                        "before scheduling the review."
                    ),
                    progress_messages=[
                        "Integration check completed; Google Calendar setup is required."
                    ],
                    integrations=requirements,
                    session_id=state.session_id,
                )
            return (
                "Schedule a care-team review for the previous result. Ask for the date, "
                "time, duration, and attendee before preparing the calendar action."
            )
        return None

    def _execute_external_tool(
        self, call: PendingToolCall, session_id: str | None = None
    ) -> dict[str, Any]:
        arguments = call.arguments
        if call.name == "finalize_administrative_review":
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
        current_description = ""
        for phase in (metadata.get("phases") or {}).values():
            for task in (phase.get("tasks") or {}).values():
                if task.get("status") in {"in_progress", "running"}:
                    current_description = str(
                        task.get("description") or task.get("name") or task.get("title") or ""
                    ).strip()
        if current_description:
            return current_description.rstrip(".") + "."
        if metadata.get("plan_status") == "completed":
            return "Planner completed the specialist workflow."
        return None

    @staticmethod
    def _describe_tool_call(call: PendingToolCall) -> str:
        arguments = call.arguments
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
            await ctx.send(
                sender,
                ChatMessage(
                    content=[
                        TextContent(
                            text="CareFlow is analyzing the request and coordinating the required specialists…"
                        )
                    ]
                ),
            )
            run = await service.receive(
                sender,
                msg.text().strip(),
            )
            if run.content:
                content = [TextContent(text=run.content)]
                if settings.enable_interactive_cards:
                    if run.tool_calls:
                        content.append(approval_card(
                            [service._describe_tool_call(call) for call in run.tool_calls],
                            session_id=run.session_id,
                        ))
                    else:
                        content.append(workflow_result_card(
                            run.content,
                            activity=run.progress_messages,
                            integrations=run.integrations,
                            execution_results=run.execution_results,
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
