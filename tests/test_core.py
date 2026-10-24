from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    # The bundled test runtime can stall while constructing Proactor's fallback
    # socketpair. Selector is sufficient for these deterministic async tests.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from agents.agent_1_ehr_search import EHRSearchAgent
from agents.agent_2_math_analytics import MathAnalyticsAgent
from agents.agent_3_clinical_triage import ClinicalTriageAgent
from agents.agent_5_workspace_sync import ApprovalRequired, PreparedAction, WorkspaceSyncAgent
from agents.agent_6_compliance_audit import ComplianceAuditAgent
from agents.supervisor_agent import ASIOnePlannerClient, SupervisorService
from services.integration_advisor import IntegrationAdvisor
from utils.asi_cards import approval_card, outcome_card, workflow_result_card
from utils.dataset_loader import DatasetLoader, DatasetValidationError
from utils.pdf_builder import build_report
from services.workflow_orchestrator import WorkflowOrchestrator


def sample_frame() -> pd.DataFrame:
    common = {
        "date_of_birth": "01-01-1980",
        "gender_identity": "Female",
        "blood_type": "O-",
        "patient_email": "patient@example.test",
        "contact_allowed": True,
        "sms_consent": True,
        "email_consent": True,
        "consent_status": "verified",
        "clinical_priority": "normal",
        "acuity_score": 2,
        "room_number": 101,
        "assigned_clinician": "Clinician-001",
        "medication": "Example",
        "human_review_required": False,
        "escalation_required": False,
        "synthetic_data_flag": True,
    }
    return pd.DataFrame([
        dict(common, record_id="R1", patient_id="P1", patient_full_name="Alex Doe",
             age_at_admission=44, primary_condition="Diabetes", encounter_id="E1",
             admission_date="01-01-2024", discharge_date="11-01-2024",
             length_of_stay_days=10, admission_type="Emergency", facility_name="North",
             payor_name="Plan A", billing_amount_usd=1000.0, test_result="Abnormal"),
        dict(common, record_id="R2", patient_id="P2", patient_full_name="Sam Doe",
             age_at_admission=65, primary_condition="Cancer", encounter_id="E2",
             admission_date="01-02-2024", discharge_date="21-02-2024",
             length_of_stay_days=20, admission_type="Elective", facility_name="South",
             payor_name="Plan B", billing_amount_usd=3000.0, test_result="Normal"),
    ])


class CoreTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / ".tmp" / "tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=test_root)
        self.path = Path(self.tmp.name) / "data.csv"
        sample_frame().to_csv(self.path, index=False)
        self.loader = DatasetLoader(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loader_and_filter(self):
        self.assertEqual(self.loader.row_count, 2)
        result = self.loader.filter(age_at_admission__gte=60)
        self.assertEqual(result.iloc[0]["patient_id"], "P2")

    def test_sqlite_index_contains_validated_dataset(self):
        destination = Path(self.tmp.name) / "healthcare.sqlite"
        self.loader.build_sqlite_index(destination)
        connection = sqlite3.connect(destination)
        try:
            row_count = connection.execute("SELECT COUNT(*) FROM encounters").fetchone()[0]
            indexes = connection.execute("PRAGMA index_list(encounters)").fetchall()
        finally:
            connection.close()
        self.assertEqual(row_count, 2)
        self.assertGreaterEqual(len(indexes), 1)

    def test_parquet_cache_round_trip(self):
        destination = Path(self.tmp.name) / "healthcare.parquet"
        self.loader.build_parquet_cache(destination)
        cached = DatasetLoader(self.path, parquet_path=destination)
        self.assertEqual(cached.row_count, 2)
        self.assertEqual(
            cached.exact_match("patient_id", "P2").iloc[0]["record_id"], "R2"
        )

    def test_invalid_boolean_is_rejected(self):
        frame = sample_frame()
        frame["email_consent"] = frame["email_consent"].astype("object")
        frame.loc[0, "email_consent"] = "maybe"
        invalid = Path(self.tmp.name) / "invalid.csv"
        frame.to_csv(invalid, index=False)
        with self.assertRaises(DatasetValidationError):
            DatasetLoader(invalid).row_count

    def test_missing_patient_is_explicit(self):
        result = EHRSearchAgent(self.loader).patient_summary("Missing Person")
        self.assertEqual(result["status"], "not_found")

    def test_analytics(self):
        analytics = MathAnalyticsAgent(self.loader)
        self.assertEqual(analytics.abnormal_result_percentage(), 50.0)
        self.assertEqual(analytics.average_length_of_stay(), 15.0)

    def test_billing_summary_preserves_threshold_filter(self):
        analytics = MathAnalyticsAgent(self.loader)
        result = analytics.handle_text(
            "Give count and total billing grouped by payor for records above $2,000"
        )
        self.assertEqual(
            result["criteria"], {"billing_amount_usd__gt": 2000.0}
        )
        self.assertEqual(
            result["result"],
            {
                "Plan B": {
                    "record_count": 1,
                    "total_billing_usd": 3000.0,
                    "average_billing_usd": 3000.0,
                }
            },
        )

    def test_specialists_accept_planner_text(self):
        ehr = EHRSearchAgent(self.loader)
        result = ehr.handle_text("Find abnormal stays longer than 5 days")
        self.assertEqual(result["count"], 1)
        analytics = MathAnalyticsAgent(self.loader)
        result = analytics.handle_text("What proportion of test results were abnormal?")
        self.assertEqual(result["result"], 50.0)
        triage = ClinicalTriageAgent(self.loader)
        self.assertEqual(triage.assess_patient("P1")["status"], "ok")

    def test_advanced_workflow_wires_all_deterministic_specialists(self):
        orchestrator = WorkflowOrchestrator(self.loader)
        orchestrator.documents = FakeDocuments(Path(self.tmp.name) / "review.pdf")
        result = orchestrator.prepare_advanced_review(
            minimum_days=5, spreadsheet_id="sheet-1", prepare_outreach=True
        )
        self.assertEqual(result.status, "awaiting_human_approval")
        self.assertEqual(result.summary["matching_records"], 1)
        self.assertEqual(len(result.summary["triage"]), 1)
        self.assertEqual({action.action for action in result.prepared_actions}, {"sheets_append", "gmail_send"})

    def test_approved_action_batch_runs_with_bounded_parallelism(self):
        orchestrator = WorkflowOrchestrator(self.loader)
        orchestrator.workspace = SlowWorkspace(delay=0.12)
        audit = FakeCompliance(allowed=True)
        orchestrator.compliance = audit
        actions = [
            PreparedAction("calendar_create_event", {"sequence": index})
            for index in range(4)
        ]
        started = time.perf_counter()
        results = orchestrator.execute_approved_actions(
            actions, approved=True, max_workers=4
        )
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.35)
        self.assertEqual([result["sequence"] for result in results], list(range(4)))
        self.assertEqual(len(audit.events), 4)

    def test_contact_consent(self):
        result = ComplianceAuditAgent().authorize_contact(
            {"patient_id": "P1", "contact_allowed": True, "email_consent": False},
            "email",
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "email_consent_missing")

    def test_string_false_cannot_bypass_consent(self):
        result = ComplianceAuditAgent(self.loader).authorize_contact(
            {"patient_id": "P1", "contact_allowed": "true", "email_consent": "false"},
            "email",
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "email_consent_missing")

    def test_external_action_requires_approval(self):
        agent = WorkspaceSyncAgent()
        action = agent.prepare_email("person@example.test", "Subject", "Body")
        with self.assertRaises(ApprovalRequired):
            agent.execute(action)

    def test_interactive_cards_use_official_metadata_envelope(self):
        approval = approval_card(["generate a review package"], session_id="session-1")
        self.assertEqual(approval.metadata["card_protocol_version"], "1")
        self.assertEqual(approval.metadata["card_kind"], "review")
        payload = json.loads(approval.metadata["card_payload"])
        self.assertEqual(payload["approve_cta"]["selection"]["action"], "approve")
        self.assertEqual(payload["reject_cta"]["selection"]["action"], "deny")

        outcome = outcome_card("Finished safely", session_id="session-1")
        self.assertEqual(outcome.metadata["card_kind"], "custom")
        self.assertEqual(outcome.metadata["is_terminal"], "true")

    def test_workflow_card_contains_visual_trace_and_actions(self):
        card = workflow_result_card(
            """Billing summary\n\n| Payor | Total Billing |\n|---|---:|\n| Plan A | $10,000 |\n| Plan B | $5,000 |""",
            activity=["EHR Search selected 2 records", "Math Analytics grouped 2 payors"],
            session_id="session-1",
        )
        payload = json.loads(card.metadata["card_payload"])
        encoded = json.dumps(payload)
        self.assertEqual(card.metadata["card_kind"], "custom")
        self.assertNotIn("is_terminal", card.metadata)
        self.assertIn("Agent activity", encoded)
        self.assertIn("Total Billing by Payor", encoded)
        self.assertIn("generate_pdf_report", encoded)
        self.assertIn("save_to_google_sheets", encoded)

    def test_integration_advisor_only_prompts_for_needed_services(self):
        runtime = SimpleNamespace(
            enable_google_actions=False,
            google_service_account_file="",
            google_delegated_user="",
        )
        advisor = IntegrationAdvisor(runtime)
        self.assertEqual(
            advisor.requirements_for("Analyze billing above $10,000 by payor"), []
        )
        self.assertEqual(
            advisor.requirements_for("Analyze cases with missing email consent"), []
        )
        requirements = advisor.requirements_for(
            "Create a PDF and email it, then save the results to Google Sheets"
        )
        status = {item.key: item.status for item in requirements}
        self.assertEqual(status["documents"], "ready")
        self.assertEqual(status["gmail"], "setup_required")
        self.assertEqual(status["sheets"], "setup_required")

    def test_planner_progress_callback_receives_execution_trace(self):
        planner = FakePlanner([[
            {
                "choices": [],
                "metadata": {
                    "type": "plan_state",
                    "plan_status": "in_progress",
                    "phases": {
                        "0": {
                            "tasks": {
                                "0": {
                                    "status": "running",
                                    "description": "Searching grounded records",
                                }
                            }
                        }
                    },
                },
            },
            {"choices": [{"delta": {"content": "Finished safely."}}]},
        ]])
        service = SupervisorService(ehr=EHRSearchAgent(self.loader), planner=planner)
        progress = []

        async def capture(message):
            progress.append(message)

        result = asyncio.run(service.receive("trace-sender", "Analyze records", capture))
        self.assertEqual(result.content, "Finished safely.")
        self.assertEqual(progress, result.progress_messages)
        self.assertIn("Searching grounded records", progress[0])

    def test_supervisor_rejects_progress_only_planner_completion(self):
        planner = FakePlanner([[
            {
                "choices": [],
                "metadata": {
                    "type": "plan_state",
                    "plan_status": "in_progress",
                    "phases": {
                        "0": {
                            "tasks": {
                                "0": {
                                    "status": "running",
                                    "description": "Analyzing billing and length of stay",
                                }
                            }
                        }
                    },
                },
            }
        ]])
        service = SupervisorService(ehr=EHRSearchAgent(self.loader), planner=planner)

        with self.assertRaisesRegex(
            RuntimeError,
            "without a final answer or actionable tool call",
        ):
            asyncio.run(service.receive("progress-only", "Analyze billing"))

    def test_planner_terminal_delta_detection_ignores_plan_status(self):
        self.assertFalse(ASIOnePlannerClient._has_terminal_delta({
            "choices": [],
            "metadata": {"type": "plan_state", "plan_status": "in_progress"},
        }))
        self.assertTrue(ASIOnePlannerClient._has_terminal_delta({
            "choices": [{"delta": {"content": "Analysis complete."}}],
        }))
        self.assertTrue(ASIOnePlannerClient._has_terminal_delta({
            "choices": [{"delta": {"tool_calls": [{"id": "call-1"}]}}],
        }))

    def test_card_json_approval_is_understood(self):
        self.assertTrue(SupervisorService._approval_decision(
            '{"action":"approve","session_id":"session-1"}'
        ))
        self.assertFalse(SupervisorService._approval_decision(
            '@careflow {"action":"deny","session_id":"session-1"}'
        ))

    def test_asi_stream_ignores_non_json_status_markers(self):
        self.assertIsNone(ASIOnePlannerClient._decode_sse_line("data: [KEEPALIVE]"))
        self.assertIsNone(ASIOnePlannerClient._decode_sse_line("data: 42"))
        self.assertEqual(
            ASIOnePlannerClient._decode_sse_line(
                'data: {"choices":[{"delta":{"content":"ok"}}]}'
            )["choices"][0]["delta"]["content"],
            "ok",
        )

    def test_internal_review_package_requires_approval_and_is_audited(self):
        tool_call = {
            "id": "review-1",
            "type": "function",
            "function": {
                "name": "finalize_administrative_review",
                "arguments": '{"minimum_days":5,"max_pdf_cases":1}',
            },
        }
        planner = FakePlanner([
            [{"choices": [{"delta": {"tool_calls": [tool_call]}}]}],
            [{"choices": [{"delta": {"content": "Review package finalized."}}]}],
        ])
        service = SupervisorService(ehr=EHRSearchAgent(self.loader), planner=planner)
        audit = FakeCompliance(allowed=True)
        service.compliance = audit

        proposed = asyncio.run(service.receive("review-sender", "Create the review"))
        self.assertIn("Approval required", proposed.content)
        self.assertEqual(proposed.tool_calls[0].name, "finalize_administrative_review")
        completed = asyncio.run(service.receive(
            "review-sender", '{"action":"approve"}'
        ))
        self.assertEqual(completed.content, "Review package finalized.")
        self.assertEqual(audit.events[0]["approved"], True)
        self.assertEqual(audit.events[0]["result"]["status"], "completed")

    def test_pdf_report_is_readable(self):
        from pypdf import PdfReader

        output = Path(self.tmp.name) / "report.pdf"
        build_report(
            "Patient Discharge Summary",
            [("Patient", {"Patient ID": "P1", "Name": "Alex Doe"})],
            output,
        )
        self.assertTrue(output.exists())
        text = "\n".join(page.extract_text() or "" for page in PdfReader(output).pages)
        self.assertIn("Patient Discharge Summary", text)

    def test_supervisor_denial_resumes_same_planner_session(self):
        tool_call = {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "send_gmail_outreach",
                "arguments": '{"patient_id":"P1","to":"p@example.test","subject":"Hi","body":"Body"}',
            },
        }
        planner = FakePlanner([
            [
                {"choices": [], "metadata": {"type": "plan_state", "plan_status": "in_progress", "phases": {"0": {"tasks": {"0": {"status": "completed"}}}}}},
                {"choices": [{"delta": {"tool_calls": [tool_call]}, "finish_reason": "tool_calls"}]},
            ],
            [{"choices": [{"delta": {"content": "Action cancelled safely."}, "finish_reason": "stop"}]}],
        ])
        service = SupervisorService(ehr=EHRSearchAgent(self.loader), planner=planner)
        audit = FakeCompliance(allowed=True)
        service.compliance = audit

        first = asyncio.run(service.receive("sender-1", "Send the email"))
        self.assertIn("Approval required", first.content)
        second = asyncio.run(service.receive("sender-1", "deny"))
        self.assertEqual(second.content, "Action cancelled safely.")
        self.assertEqual(planner.session_ids[0], planner.session_ids[1])
        self.assertEqual(audit.events[0]["approved"], False)
        self.assertEqual(audit.events[0]["planner_session_id"], planner.session_ids[0])
        tool_messages = [m for m in planner.messages_seen[1] if m["role"] == "tool"]
        self.assertIn("denied_by_user", tool_messages[0]["content"])

    def test_supervisor_approval_still_blocks_missing_consent(self):
        tool_call = {
            "id": "call-2",
            "type": "function",
            "function": {
                "name": "send_gmail_outreach",
                "arguments": '{"patient_id":"P1","to":"p@example.test","subject":"Hi","body":"Body"}',
            },
        }
        planner = FakePlanner([
            [{"choices": [{"delta": {"tool_calls": [tool_call]}, "finish_reason": "tool_calls"}]}],
            [{"choices": [{"delta": {"content": "Consent blocked the send."}, "finish_reason": "stop"}]}],
        ])
        service = SupervisorService(ehr=EHRSearchAgent(self.loader), planner=planner)
        audit = FakeCompliance(allowed=False)
        service.compliance = audit
        workspace = FakeWorkspace()
        service.workspace = workspace

        asyncio.run(service.receive("sender-2", "Send the email"))
        result = asyncio.run(service.receive("sender-2", "approve"))
        self.assertEqual(result.content, "Consent blocked the send.")
        self.assertEqual(workspace.executions, 0)
        self.assertEqual(audit.events[0]["result"]["status"], "blocked_by_consent")

    def test_supervisor_executes_independent_approved_tools_concurrently(self):
        def calendar_call(index):
            return {
                "id": f"calendar-{index}",
                "type": "function",
                "function": {
                    "name": "create_calendar_review",
                    "arguments": (
                        '{"patient_id":"P1","summary":"Review %d",'
                        '"start":"2026-10-20T10:00:00+05:30",'
                        '"end":"2026-10-20T10:30:00+05:30",'
                        '"attendee_email":null}' % index
                    ),
                },
            }

        planner = FakePlanner([
            [{"choices": [{"delta": {"tool_calls": [calendar_call(1), calendar_call(2)]}}]}],
            [{"choices": [{"delta": {"content": "Both reviews were created."}}]}],
        ])
        service = SupervisorService(
            ehr=EHRSearchAgent(self.loader),
            planner=planner,
            allow_google_actions=True,
        )
        service.workspace = SlowWorkspace(delay=0.15)
        service.compliance = FakeCompliance(allowed=True)
        asyncio.run(service.receive("parallel-sender", "Create both reviews"))
        started = time.perf_counter()
        result = asyncio.run(service.receive("parallel-sender", "approve"))
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.28)
        self.assertEqual(result.content, "Both reviews were created.")


class FakePlanner:
    def __init__(self, runs):
        self.runs = list(runs)
        self.session_ids = []
        self.messages_seen = []

    async def stream_async(self, messages, session_id, tools=None):
        self.session_ids.append(session_id)
        self.messages_seen.append([dict(message) for message in messages])
        for event in self.runs.pop(0):
            yield event


class FakeCompliance:
    def __init__(self, allowed: bool):
        self.allowed = allowed
        self.events = []

    def authorize_contact(self, record, channel):
        return {"allowed": self.allowed, "channel": channel, "patient_id": record.get("patient_id")}

    def append_event(self, event, path=None):
        self.events.append(event)
        return Path("audit.jsonl")


class FakeWorkspace:
    def __init__(self):
        self.executions = 0

    def prepare_email(self, to, subject, body):
        from agents.agent_5_workspace_sync import PreparedAction
        return PreparedAction("gmail_send", {"to": to, "subject": subject, "body": body})

    def execute(self, action, *, approved=False):
        self.executions += 1
        return {"status": "sent"}


class FakeDocuments:
    def __init__(self, path: Path):
        self.path = path

    def case_review(self, records, output_name="review.pdf", max_cases=100):
        self.path.write_bytes(b"%PDF-test")
        return self.path


class SlowWorkspace:
    def __init__(self, delay: float):
        self.delay = delay

    def execute(self, action, *, approved=False):
        if not approved:
            raise ApprovalRequired("approval required")
        time.sleep(self.delay)
        return {"status": "created", "sequence": action.payload.get("sequence")}

    def prepare_calendar_event(self, **payload):
        return PreparedAction("calendar_create_event", payload)


if __name__ == "__main__":
    unittest.main()

