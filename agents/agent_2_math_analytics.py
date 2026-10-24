"""Pandas-backed healthcare analytics specialist."""

from __future__ import annotations

import re
from math import sqrt
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

    def operational_analysis(
        self,
        *,
        billing_threshold: float = 10_000.0,
        anomaly_z_threshold: float = 3.0,
        minimum_anomaly_group_size: int = 30,
        minimum_practical_los_delta_days: float = 1.0,
    ) -> dict[str, Any]:
        """Return the complete deterministic analysis used by the demo workflow."""

        billing_rows = self.frame.loc[
            self.frame["billing_amount_usd"].gt(billing_threshold)
        ]

        def billing_groups(column: str) -> dict[str, dict[str, float | int]]:
            grouped = (
                billing_rows.groupby(column, dropna=False)["billing_amount_usd"]
                .agg(["count", "sum", "mean"])
                .sort_values("sum", ascending=False)
            )
            return {
                str(key): {
                    "record_count": int(row["count"]),
                    "total_billing_usd": round(float(row["sum"]), 2),
                    "average_billing_usd": round(float(row["mean"]), 2),
                }
                for key, row in grouped.iterrows()
            }

        top_columns = [
            "record_id",
            "billing_amount_usd",
            "facility_name",
            "payor_name",
            "primary_condition",
            "admission_type",
        ]
        top_outliers = self.loader.records(
            billing_rows.nlargest(3, "billing_amount_usd")[top_columns], limit=3
        )

        system_average = float(self.frame["length_of_stay_days"].mean())
        facility_rows: dict[str, dict[str, float | int | bool]] = {}
        for facility, rows in self.frame.groupby("facility_name", dropna=False):
            rest = self.frame.loc[self.frame["facility_name"].ne(facility)]
            count = int(len(rows))
            rest_count = int(len(rest))
            mean = float(rows["length_of_stay_days"].mean())
            rest_mean = float(rest["length_of_stay_days"].mean())
            delta = mean - rest_mean
            standard_error = sqrt(
                float(rows["length_of_stay_days"].var(ddof=1)) / count
                + float(rest["length_of_stay_days"].var(ddof=1)) / rest_count
            )
            ci_low = delta - 1.96 * standard_error
            ci_high = delta + 1.96 * standard_error
            facility_rows[str(facility)] = {
                "record_count": count,
                "average_los_days": round(mean, 2),
                "delta_vs_system_days": round(mean - system_average, 2),
                "delta_vs_rest_days": round(delta, 2),
                "difference_95_ci_low_days": round(ci_low, 2),
                "difference_95_ci_high_days": round(ci_high, 2),
                "significantly_higher": bool(
                    ci_low > 0 and delta >= minimum_practical_los_delta_days
                ),
            }

        anomaly_frame = self.frame.copy()
        groups = anomaly_frame.groupby(
            ["primary_condition", "admission_type"], dropna=False
        )["billing_amount_usd"]
        anomaly_frame["anomaly_group_count"] = groups.transform("size")
        anomaly_frame["anomaly_group_mean"] = groups.transform("mean")
        anomaly_frame["anomaly_group_std"] = groups.transform("std")
        anomaly_frame["billing_z_score"] = (
            anomaly_frame["billing_amount_usd"]
            - anomaly_frame["anomaly_group_mean"]
        ) / anomaly_frame["anomaly_group_std"]
        anomalies = anomaly_frame.loc[
            anomaly_frame["anomaly_group_count"].ge(minimum_anomaly_group_size)
            & anomaly_frame["billing_z_score"].gt(anomaly_z_threshold)
        ].sort_values("billing_z_score", ascending=False)
        anomaly_columns = top_columns + [
            "anomaly_group_count",
            "anomaly_group_mean",
            "anomaly_group_std",
            "billing_z_score",
        ]

        return {
            "operation": "operational_analysis",
            "billing": {
                "filter": {"billing_amount_usd__gt": billing_threshold},
                "record_count": int(len(billing_rows)),
                "by_payor": billing_groups("payor_name"),
                "by_facility": billing_groups("facility_name"),
                "top_three_records": top_outliers,
            },
            "length_of_stay": {
                "system_average_days": round(system_average, 2),
                "minimum_practical_delta_days": minimum_practical_los_delta_days,
                "comparison_method": (
                    "95% confidence interval for each facility mean versus the rest "
                    "of the system, plus a minimum practical difference"
                ),
                "facilities": facility_rows,
            },
            "billing_anomalies": {
                "rule": (
                    "Within each primary-condition + admission-type group with at "
                    f"least {minimum_anomaly_group_size} records, flag billing z-score "
                    f"> {anomaly_z_threshold:g} using the sample standard deviation."
                ),
                "record_count": int(len(anomalies)),
                "maximum_observed_z_score": round(
                    float(anomaly_frame["billing_z_score"].max()), 2
                ),
                "top_records": self.loader.records(
                    anomalies[anomaly_columns], limit=3
                ),
            },
        }

    @staticmethod
    def is_operational_analysis_request(text: str) -> bool:
        query = text.casefold()
        return (
            ("billing" in query or "bill" in query)
            and ("length of stay" in query or "average stay" in query)
            and any(term in query for term in ("anomal", "outlier", "unusually high"))
        )

    @staticmethod
    def format_operational_analysis(result: dict[str, Any]) -> str:
        billing = result["billing"]
        los = result["length_of_stay"]
        anomalies = result["billing_anomalies"]
        lines = [
            "## Billing above $10,000",
            "",
            "### By payor",
            "",
            "| Payor | Records | Total billing (USD) | Average billing (USD) |",
            "|---|---:|---:|---:|",
        ]
        for name, values in billing["by_payor"].items():
            lines.append(
                f"| {name} | {values['record_count']:,} | "
                f"${values['total_billing_usd']:,.2f} | "
                f"${values['average_billing_usd']:,.2f} |"
            )
        lines.extend([
            "",
            "### By facility",
            "",
            "| Facility | Records | Total billing (USD) | Average billing (USD) |",
            "|---|---:|---:|---:|",
        ])
        for name, values in billing["by_facility"].items():
            lines.append(
                f"| {name} | {values['record_count']:,} | "
                f"${values['total_billing_usd']:,.2f} | "
                f"${values['average_billing_usd']:,.2f} |"
            )
        lines.extend([
            "",
            f"Filtered record count: **{billing['record_count']:,}**.",
            "",
            "### Top three billing records",
            "",
            "| Record | Amount | Facility | Payor | Condition / admission |",
            "|---|---:|---|---|---|",
        ])
        for row in billing["top_three_records"]:
            lines.append(
                f"| {row['record_id']} | ${row['billing_amount_usd']:,.2f} | "
                f"{row['facility_name']} | {row['payor_name']} | "
                f"{row['primary_condition']} / {row['admission_type']} |"
            )
        lines.extend([
            "",
            "## Facility length of stay",
            "",
            f"System-wide average: **{los['system_average_days']:.2f} days**.",
            "",
            "| Facility | Records | Average LOS | Difference vs system | Significantly higher? |",
            "|---|---:|---:|---:|---|",
        ])
        for name, values in los["facilities"].items():
            lines.append(
                f"| {name} | {values['record_count']:,} | "
                f"{values['average_los_days']:.2f} days | "
                f"{values['delta_vs_system_days']:+.2f} days | "
                f"{'Yes' if values['significantly_higher'] else 'No'} |"
            )
        significant = [
            name for name, values in los["facilities"].items()
            if values["significantly_higher"]
        ]
        lines.extend([
            "",
            (
                "Significantly higher facilities: **"
                + (", ".join(significant) if significant else "none")
                + "**. The rule requires the 95% confidence interval versus the rest "
                f"of the system to be above zero and at least "
                f"{los['minimum_practical_delta_days']:.1f} day higher."
            ),
            "",
            "## Billing anomalies",
            "",
            anomalies["rule"],
            "",
            f"Flagged records: **{anomalies['record_count']:,}**. Maximum observed "
            f"within-group z-score: **{anomalies['maximum_observed_z_score']:.2f}**.",
        ])
        if not anomalies["top_records"]:
            lines.append(
                "No record meets the stated anomaly rule, so no billing anomaly is "
                "claimed from this dataset."
            )
        return "\n".join(lines)

    def handle_text(self, text: str) -> dict[str, Any]:
        """Route common planner directives to deterministic calculations."""

        query = text.casefold()
        if self.is_operational_analysis_request(text):
            return self.operational_analysis()
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
        if operation == "operational_analysis":
            return service.operational_analysis(
                billing_threshold=float(payload.get("billing_threshold", 10_000)),
                anomaly_z_threshold=float(payload.get("anomaly_z_threshold", 3)),
                minimum_anomaly_group_size=int(
                    payload.get("minimum_anomaly_group_size", 30)
                ),
                minimum_practical_los_delta_days=float(
                    payload.get("minimum_practical_los_delta_days", 1)
                ),
            )
        raise ValueError(f"Unsupported analytics operation: {operation}")

    return build_text_uagent("healthcare-math-analytics", handle, slot=2)


if __name__ == "__main__":  # pragma: no cover
    build_uagent().run()

