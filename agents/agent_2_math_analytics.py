"""Pandas-backed healthcare analytics specialist."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from config import settings
from agents.chat_protocol import build_text_uagent
from utils.dataset_loader import DatasetLoader


class MathAnalyticsAgent:
    def __init__(self, loader: DatasetLoader | None = None):
        self.loader = loader or DatasetLoader(
            settings.dataset_path, settings.sqlite_path, settings.parquet_path
        )

    @property
    def frame(self) -> pd.DataFrame:
        return self.loader.frame

    def average_length_of_stay(self, by: str | None = None) -> Any:
        if by:
            self.loader._require_columns([by])
            result = (
                self.frame.groupby(by, dropna=False)["length_of_stay_days"]
                .mean()
                .sort_values(ascending=False)
            )
            return {str(key): round(float(value), 2) for key, value in result.items()}
        return round(float(self.frame["length_of_stay_days"].mean()), 2)

    def abnormal_result_percentage(self, **criteria: Any) -> float | None:
        population = self.loader.filter(**criteria) if criteria else self.frame
        if population.empty:
            return None
        abnormal = population["test_result"].astype("string").str.casefold().eq("abnormal")
        return round(float(abnormal.mean() * 100), 2)

    def billing_summary(
        self, by: str, **criteria: Any
    ) -> dict[str, dict[str, float | int]]:
        self.loader._require_columns([by])
        population = self.loader.filter(**criteria) if criteria else self.frame
        grouped = population.groupby(by, dropna=False)["billing_amount_usd"].agg(
            ["count", "sum", "mean"]
        )
        return {
            str(key): {
                "record_count": int(row["count"]),
                "total_billing_usd": round(float(row["sum"]), 2),
                "average_billing_usd": round(float(row["mean"]), 2),
            }
            for key, row in grouped.iterrows()
        }

    def admission_counts(self, by: str) -> dict[str, int]:
        self.loader._require_columns([by])
        counts = self.frame.groupby(by, dropna=False).size().sort_values(ascending=False)
        return {str(key): int(value) for key, value in counts.items()}

    def compare_conditions(self, conditions: list[str]) -> dict[str, dict[str, float | int]]:
        subset = self.loader.filter(primary_condition__in=conditions)
        grouped = subset.groupby("primary_condition").agg(
            admissions=("record_id", "size"),
            average_stay_days=("length_of_stay_days", "mean"),
            average_bill_usd=("billing_amount_usd", "mean"),
        )
        return {
            str(key): {
                "admissions": int(row["admissions"]),
                "average_stay_days": round(float(row["average_stay_days"]), 2),
                "average_bill_usd": round(float(row["average_bill_usd"]), 2),
            }
            for key, row in grouped.iterrows()
        }

    def top_records(self, column: str, limit: int = 10) -> list[dict[str, Any]]:
        self.loader._require_columns([column])
        rows = self.frame.sort_values(column, ascending=False)
        return self.loader.records(rows, limit=max(1, min(limit, 100)))

    def handle_text(self, text: str) -> dict[str, Any]:
        """Route common planner directives to deterministic calculations."""

        query = text.casefold()
        conditions = [
            value for value in self.frame["primary_condition"].dropna().astype(str).unique()
            if value.casefold() in query
        ]
        if ("compare" in query or "between" in query) and len(conditions) >= 2:
            return {"operation": "compare_conditions", "result": self.compare_conditions(conditions)}
        if "abnormal" in query and any(word in query for word in ("percent", "percentage", "proportion", "rate")):
            return {"operation": "abnormal_percentage", "result": self.abnormal_result_percentage()}
        if any(word in query for word in ("average stay", "average length", "mean stay")):
            group = None
            group_terms = {
                "hospital": "facility_name", "facility": "facility_name",
                "condition": "primary_condition", "admission type": "admission_type",
                "payor": "payor_name", "payer": "payor_name",
            }
            for term, column in group_terms.items():
                if any(prefix in query for prefix in (f"by {term}", f"across {term}", f"each {term}")):
                    group = column
                    break
            if group is None:
                for value in self.frame["admission_type"].dropna().astype(str).unique():
                    if value.casefold() in query:
                        subset = self.loader.filter(admission_type=value)
                        result = round(float(subset["length_of_stay_days"].mean()), 2) if not subset.empty else None
                        return {"operation": "average_length_of_stay", "filter": {"admission_type": value}, "result": result}
            return {"operation": "average_length_of_stay", "group_by": group, "result": self.average_length_of_stay(group)}
        if any(word in query for word in ("admission count", "admission volume", "most admissions", "highest number of admissions")):
            group = "facility_name"
            if "condition" in query:
                group = "primary_condition"
            elif "doctor" in query or "clinician" in query:
                group = "assigned_clinician"
            return {"operation": "admission_counts", "group_by": group, "result": self.admission_counts(group)}
        if "billing" in query or "bill" in query:
            top = re.search(r"\btop\s+(\d+)\b", query)
            if top or any(word in query for word in ("highest", "largest")):
                return {
                    "operation": "top_records",
                    "sort_by": "billing_amount_usd",
                    "result": self.top_records("billing_amount_usd", int(top.group(1)) if top else 10),
                }
            group = "payor_name" if ("payor" in query or "payer" in query or "insurance" in query) else "facility_name"
            criteria: dict[str, Any] = {}
            threshold = re.search(
                r"(?:above|over|more than|greater than|>)\s*\$?([\d,.]+)",
                query,
            )
            if threshold:
                criteria["billing_amount_usd__gt"] = float(
                    threshold.group(1).replace(",", "")
                )
            return {
                "operation": "billing_summary",
                "group_by": group,
                "criteria": criteria,
                "result": self.billing_summary(group, **criteria),
            }
        return {
            "status": "needs_input",
            "message": "Specify an average, percentage, comparison, admission-count, billing, or top-record calculation.",
        }


def build_uagent():
    service = MathAnalyticsAgent()

    def handle(payload: Any):
        if isinstance(payload, str):
            return service.handle_text(payload)
        operation = payload.get("operation")
        if operation == "average_length_of_stay":
            return {"result": service.average_length_of_stay(payload.get("by"))}
        if operation == "abnormal_percentage":
            return {"result": service.abnormal_result_percentage(**payload.get("criteria", {}))}
        if operation == "billing_summary":
            return service.billing_summary(
                payload["by"], **payload.get("criteria", {})
            )
        if operation == "admission_counts":
            return service.admission_counts(payload["by"])
        if operation == "compare_conditions":
            return service.compare_conditions(payload["conditions"])
        if operation == "top_records":
            return service.top_records(payload["column"], int(payload.get("limit", 10)))
        raise ValueError(f"Unsupported analytics operation: {operation}")

    return build_text_uagent("healthcare-math-analytics", handle, slot=2)


if __name__ == "__main__":  # pragma: no cover
    build_uagent().run()

