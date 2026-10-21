"""Administrative PDF document specialist."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from agents.chat_protocol import build_text_uagent
from config import settings
from utils.pdf_builder import build_report, warm_pdf_backend
from utils.dataset_loader import DatasetLoader


class DocumentGeneratorAgent:
    def __init__(self, loader: DatasetLoader | None = None):
        self.loader = loader or DatasetLoader(
            settings.dataset_path, settings.sqlite_path, settings.parquet_path
        )
        self.pdf_backend = warm_pdf_backend()

    def discharge_summary(self, record: Mapping[str, Any]) -> Path:
        patient_id = str(record.get("patient_id", "unknown"))
        destination = settings.ensure_output_dir() / f"discharge_summary_{patient_id}.pdf"
        return build_report(
            "Patient Discharge Summary",
            [
                ("Patient", {
                    "Patient ID": patient_id,
                    "Name": record.get("patient_full_name"),
                    "Date of birth": record.get("date_of_birth"),
                }),
                ("Encounter", {
                    "Facility": record.get("facility_name"),
                    "Admission date": record.get("admission_date"),
                    "Discharge date": record.get("discharge_date"),
                    "Length of stay (days)": record.get("length_of_stay_days"),
                    "Condition": record.get("primary_condition"),
                    "Medication": record.get("medication"),
                    "Test result": record.get("test_result"),
                }),
                ("Billing", {
                    "Payor": record.get("payor_name"),
                    "Billing amount (USD)": record.get("billing_amount_usd"),
                }),
            ],
            destination,
        )

    def itemized_invoice(self, record: Mapping[str, Any]) -> Path:
        encounter_id = str(record.get("encounter_id", "unknown"))
        destination = settings.ensure_output_dir() / f"invoice_{encounter_id}.pdf"
        return build_report(
            "Itemized Accounting Invoice",
            [
                ("Account", {
                    "Patient ID": record.get("patient_id"),
                    "Encounter ID": encounter_id,
                    "Facility": record.get("facility_name"),
                    "Payor": record.get("payor_name"),
                }),
                ("Recorded services", {
                    "Admission type": record.get("admission_type"),
                    "Length of stay (days)": record.get("length_of_stay_days"),
                    "Condition": record.get("primary_condition"),
                    "Medication": record.get("medication"),
                }),
                ("Amount", {
                    "Total recorded billing (USD)": record.get("billing_amount_usd"),
                    "Source": "Synthetic encounter dataset",
                }),
            ],
            destination,
        )

    def case_review(
        self,
        records: Iterable[Mapping[str, Any]],
        output_name: str = "administrative_case_review.pdf",
        max_cases: int = 100,
    ) -> Path:
        selected = list(records)[:max_cases]
        destination = settings.ensure_output_dir() / output_name
        sections: list[tuple[str, Mapping[str, Any]]] = [
            ("Review scope", {
                "Cases included": len(selected),
                "Selection rule": "Provided by the requesting workflow",
                "Clinical use": "Administrative review only",
            })
        ]
        for index, record in enumerate(selected, start=1):
            sections.append((f"Case {index}", {
                "Patient ID": record.get("patient_id"),
                "Encounter ID": record.get("encounter_id"),
                "Facility": record.get("facility_name"),
                "Admission date": record.get("admission_date"),
                "Discharge date": record.get("discharge_date"),
                "Length of stay (days)": record.get("length_of_stay_days"),
                "Condition": record.get("primary_condition"),
                "Test result": record.get("test_result"),
                "Billing amount (USD)": record.get("billing_amount_usd"),
                "Human review required": record.get("human_review_required"),
                "Escalation level": record.get("escalation_level"),
            }))
        return build_report("Administrative Case Review", sections, destination)

    def handle_text(self, text: str) -> dict[str, Any]:
        query = text.casefold()
        patient_match = re.search(r"\b(?:pat-\d+|p\d+)\b", text, re.IGNORECASE)
        if "case review" in query or "administrative review" in query:
            days = re.search(r"(?:over|more than|>)\s*(\d+)\s*days", query)
            minimum = int(days.group(1)) if days else 30
            records = self.loader.records(
                self.loader.filter(length_of_stay_days__gt=minimum)
                .sort_values("length_of_stay_days", ascending=False),
                limit=100,
            )
            path = self.case_review(records, output_name=f"case_review_over_{minimum}_days.pdf")
            return {"status": "generated", "path": str(path), "cases": len(records)}
        if not patient_match:
            return {"status": "needs_input", "message": "Include a patient ID or request a long-stay case review."}
        rows = self.loader.exact_match("patient_id", patient_match.group(0))
        if rows.empty:
            return {"status": "not_found", "patient_id": patient_match.group(0)}
        record = self.loader.records(rows, limit=1)[0]
        path = self.itemized_invoice(record) if "invoice" in query else self.discharge_summary(record)
        return {"status": "generated", "path": str(path)}


def build_uagent():
    service = DocumentGeneratorAgent()

    def handle(payload: Any):
        if isinstance(payload, str):
            return service.handle_text(payload)
        operation = payload.get("operation", "discharge_summary")
        if operation == "discharge_summary":
            path = service.discharge_summary(payload["record"])
        elif operation == "itemized_invoice":
            path = service.itemized_invoice(payload["record"])
        elif operation == "case_review":
            path = service.case_review(
                payload["records"],
                output_name=payload.get("output_name", "administrative_case_review.pdf"),
                max_cases=int(payload.get("max_cases", 100)),
            )
        else:
            raise ValueError(f"Unsupported document operation: {operation}")
        return {"status": "generated", "path": str(path)}

    return build_text_uagent("healthcare-document-generator", handle, slot=4)


if __name__ == "__main__":  # pragma: no cover
    build_uagent().run()

