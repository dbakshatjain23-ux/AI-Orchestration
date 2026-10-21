"""Coordinates deterministic specialists for multi-step administrative workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agents.agent_1_ehr_search import EHRSearchAgent
from agents.agent_3_clinical_triage import ClinicalTriageAgent
from agents.agent_4_doc_generator import DocumentGeneratorAgent
from agents.agent_5_workspace_sync import ApprovalRequired, PreparedAction, WorkspaceSyncAgent
from agents.agent_6_compliance_audit import ComplianceAuditAgent
from config import settings
from utils.dataset_loader import DatasetLoader


ADVANCED_WORKFLOW_COLUMNS = [
    "patient_id", "patient_full_name", "patient_email", "date_of_birth",
    "age_at_admission", "encounter_id", "facility_name", "admission_date",
    "discharge_date", "length_of_stay_days", "admission_type",
    "primary_condition", "medication", "test_result", "billing_amount_usd",
    "payor_name", "acuity_score", "clinical_priority", "human_review_required",
    "human_review_reason", "escalation_required", "escalation_level",
    "escalation_owner_role", "contact_allowed", "email_consent", "consent_status",
]


@dataclass
class WorkflowResult:
    status: str
    summary: dict[str, Any]
    generated_files: list[str]
    prepared_actions: list[PreparedAction]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "generated_files": self.generated_files,
            "prepared_actions": [asdict(action) for action in self.prepared_actions],
        }


class WorkflowOrchestrator:
    def __init__(self, loader: DatasetLoader | None = None):
        self.loader = loader or DatasetLoader(
            settings.dataset_path, settings.sqlite_path, settings.parquet_path
        )
        self.ehr = EHRSearchAgent(self.loader)
        self.triage = ClinicalTriageAgent(self.loader)
        self.documents = DocumentGeneratorAgent(self.loader)
        self.workspace = WorkspaceSyncAgent()
        self.compliance = ComplianceAuditAgent(self.loader)

    def prepare_discharge_workflow(self, patient_id: str) -> WorkflowResult:
        rows = self.ehr.find_patient_by_id(patient_id)
        if rows.empty:
            return WorkflowResult(
                status="not_found",
                summary={"message": f"No record matches patient ID '{patient_id}'."},
                generated_files=[],
                prepared_actions=[],
            )
        record = self.loader.records(rows.sort_values("admission_date"), limit=1)[0]
        triage = self.triage.assess(record)
        report = self.documents.discharge_summary(record)
        consent = self.compliance.authorize_contact(record, "email")
        actions: list[PreparedAction] = []
        if consent["allowed"]:
            actions.append(self.workspace.prepare_email(
                str(record["patient_email"]),
                "Your discharge summary is ready",
                "Your discharge summary has been prepared. Use the secure delivery channel to access it.",
                patient_id=str(record["patient_id"]),
            ))
        return WorkflowResult(
            status="awaiting_human_approval" if actions else "completed_with_contact_blocked",
            summary={"patient_id": patient_id, "triage": triage, "contact": consent},
            generated_files=[str(report)],
            prepared_actions=actions,
        )

    def prepare_advanced_review(
        self,
        minimum_days: int = 30,
        spreadsheet_id: str | None = None,
        prepare_outreach: bool = True,
        max_pdf_cases: int = 100,
        max_outreach_actions: int = 100,
    ) -> WorkflowResult:
        """Execute the complete deterministic half of the Category-J workflow."""

        rows = self.loader.filter(
            length_of_stay_days__gt=minimum_days,
            test_result="Abnormal",
        ).sort_values(["length_of_stay_days", "billing_amount_usd"], ascending=False)
        projected = rows.loc[:, [
            column for column in ADVANCED_WORKFLOW_COLUMNS if column in rows.columns
        ]]
        review_records = self.loader.records(projected, limit=max_pdf_cases)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="workflow-prepare") as pool:
            triage_future = pool.submit(self._assess_records, review_records)
            report_future = pool.submit(
                self.documents.case_review,
                review_records,
                f"abnormal_long_stay_review_over_{minimum_days}_days.pdf",
                max_pdf_cases,
            )
            review_triage = triage_future.result()
            report = report_future.result()
        actions: list[PreparedAction] = []
        blocked_contacts: list[dict[str, Any]] = []
        if spreadsheet_id and not projected.empty:
            sheet_records = self.loader.records(projected, limit=len(projected))
            actions.append(self.workspace.prepare_sheet_append(
                spreadsheet_id,
                [[
                    record.get("patient_id"), record.get("encounter_id"),
                    record.get("facility_name"), record.get("length_of_stay_days"),
                    record.get("test_result"), record.get("acuity_score"),
                    record.get("escalation_level"), record.get("billing_amount_usd"),
                ] for record in sheet_records],
                worksheet_name="Abnormal long stays",
            ))
        if prepare_outreach:
            outreach_records = self.loader.records(projected, limit=max_outreach_actions)
            for record in outreach_records:
                consent = self.compliance.authorize_contact(record, "email")
                email = record.get("patient_email")
                if consent["allowed"] and email:
                    actions.append(self.workspace.prepare_email(
                        str(email),
                        "Follow-up after your recent encounter",
                        "Your care team has prepared a follow-up. Please use the secure patient channel for clinical details.",
                        patient_id=str(record["patient_id"]),
                    ))
                else:
                    blocked_contacts.append(consent)
        if "escalation_level" in rows.columns:
            l2_escalations = int((
                rows["escalation_required"].eq(True)
                & rows["escalation_level"].astype("string").str.casefold().eq("l2")
            ).sum())
        else:
            l2_escalations = 0
        return WorkflowResult(
            status="awaiting_human_approval" if actions else "completed",
            summary={
                "selection": f"length_of_stay_days > {minimum_days} AND test_result = Abnormal",
                "matching_records": int(len(rows)),
                "cases_in_pdf": len(review_records),
                "pdf_truncated": len(rows) > len(review_records),
                "triage_evaluated": int(len(rows)),
                "triage": review_triage,
                "l2_escalations": l2_escalations,
                "outreach_candidates_considered": min(len(rows), max_outreach_actions)
                if prepare_outreach else 0,
                "outreach_truncated": prepare_outreach and len(rows) > max_outreach_actions,
                "contact_blocked": blocked_contacts,
            },
            generated_files=[str(report)],
            prepared_actions=actions,
        )

    def prepare_long_stay_review(
        self, minimum_days: int = 30, spreadsheet_id: str | None = None
    ) -> WorkflowResult:
        rows = self.loader.filter(length_of_stay_days__gt=minimum_days).sort_values(
            ["length_of_stay_days", "billing_amount_usd"], ascending=False
        )
        records = self.loader.records(rows, limit=100)
        report = self.documents.case_review(
            records,
            output_name=f"case_review_over_{minimum_days}_days.pdf",
            max_cases=100,
        )
        actions: list[PreparedAction] = []
        if spreadsheet_id and records:
            values = [[
                record.get("patient_id"),
                record.get("encounter_id"),
                record.get("facility_name"),
                record.get("length_of_stay_days"),
                record.get("billing_amount_usd"),
                record.get("human_review_required"),
            ] for record in records]
            actions.append(
                self.workspace.prepare_sheet_append(
                    spreadsheet_id,
                    values,
                    worksheet_name="Long stay review",
                )
            )
        return WorkflowResult(
            status="awaiting_human_approval" if actions else "completed",
            summary={
                "selection": f"length_of_stay_days > {minimum_days}",
                "matching_records": int(len(rows)),
                "cases_in_pdf": len(records),
            },
            generated_files=[str(report)],
            prepared_actions=actions,
        )

    def execute_approved_actions(
        self,
        actions: list[PreparedAction],
        *,
        approved: bool,
        max_workers: int = 4,
    ) -> list[dict[str, Any]]:
        if not 1 <= max_workers <= 16:
            raise ValueError("max_workers must be between 1 and 16")
        if not actions:
            return []
        if not approved:
            raise ApprovalRequired("Human approval is required before executing actions")
        if any(action.action == "gmail_send" for action in actions):
            self.loader.frame
            self.loader._text_index("patient_id")
        worker_count = min(max_workers, len(actions))
        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="workspace-action"
        ) as pool:
            results = list(pool.map(
                lambda action: self._execute_prepared_action(action, approved=approved),
                actions,
            ))
        for action, result in zip(actions, results):
            self.compliance.append_event({
                "audit_event_type": "encounter_workflow_created",
                "action": action.action,
                "patient_id": action.payload.get("patient_id"),
                "approved": approved,
                "result": result,
            })
        return results

    def _assess_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"patient_id": record.get("patient_id"), **self.triage.assess(record)}
            for record in records
        ]

    def _execute_prepared_action(
        self, action: PreparedAction, *, approved: bool
    ) -> dict[str, Any]:
        if action.action != "gmail_send" or not action.payload.get("patient_id"):
            return self.workspace.execute(action, approved=approved)
        rows = self.ehr.find_patient_by_id(str(action.payload["patient_id"]))
        if rows.empty:
            return {"status": "blocked", "reason": "patient_not_found"}
        record = self.loader.records(rows, limit=1)[0]
        consent = self.compliance.authorize_contact(record, "email")
        if not consent["allowed"]:
            return {"status": "blocked_by_consent", "consent": consent}
        if str(record.get("patient_email", "")).casefold() != str(action.payload["to"]).casefold():
            return {"status": "blocked", "reason": "recipient_mismatch"}
        return self.workspace.execute(action, approved=approved)

