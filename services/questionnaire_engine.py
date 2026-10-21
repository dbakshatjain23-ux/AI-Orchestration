"""Deterministic evaluator for the supplied healthcare question catalogue."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from agents.agent_1_ehr_search import EHRSearchAgent
from agents.agent_2_math_analytics import MathAnalyticsAgent
from utils.dataset_loader import DatasetLoader


@dataclass
class QuestionnaireEngine:
    loader: DatasetLoader

    def __post_init__(self) -> None:
        self.ehr = EHRSearchAgent(self.loader)
        self.analytics = MathAnalyticsAgent(self.loader)

    @property
    def frame(self) -> pd.DataFrame:
        return self.loader.frame

    @staticmethod
    def _normalized(query: str) -> str:
        return re.sub(r"\s+", " ", query.strip().casefold()).rstrip("?.")

    @staticmethod
    def _needs_input(field: str, example: str) -> dict[str, Any]:
        return {
            "status": "needs_input",
            "missing": field,
            "message": f"Provide {field}, for example: {example}",
        }

    def _records(self, subset: pd.DataFrame, limit: int = 100) -> dict[str, Any]:
        return {
            "status": "ok",
            "count": int(len(subset)),
            "returned": int(min(len(subset), limit)),
            "records": self.loader.records(subset, limit=limit),
        }

    def _patient_rows(self, name: str = "Bobby Jackson") -> pd.DataFrame:
        return self.ehr.find_patient(name)

    def _patient_field(self, field: str, name: str = "Bobby Jackson") -> dict[str, Any]:
        rows = self._patient_rows(name)
        if rows.empty:
            return {"status": "not_found", "message": f"No record matches patient name '{name}'."}
        values = rows[field].dropna().unique().tolist()
        values = [value.isoformat() if isinstance(value, pd.Timestamp) else value for value in values]
        return {"status": "ok", "patient": name, field: values[0] if len(values) == 1 else values}

    @staticmethod
    def _series_dict(series: pd.Series, value_name: str = "count") -> dict[str, Any]:
        return {
            str(key): int(value) if float(value).is_integer() else round(float(value), 2)
            for key, value in series.items()
        }

    def _facility_metrics(self, subset: pd.DataFrame | None = None) -> dict[str, Any]:
        data = self.frame if subset is None else subset
        grouped = data.groupby("facility_name").agg(
            admissions=("record_id", "size"),
            average_stay_days=("length_of_stay_days", "mean"),
            total_billing_usd=("billing_amount_usd", "sum"),
            average_billing_usd=("billing_amount_usd", "mean"),
        )
        return {
            str(key): {
                "admissions": int(row["admissions"]),
                "average_stay_days": round(float(row["average_stay_days"]), 2),
                "total_billing_usd": round(float(row["total_billing_usd"]), 2),
                "average_billing_usd": round(float(row["average_billing_usd"]), 2),
            }
            for key, row in grouped.iterrows()
        }

    def answer(self, query: str) -> dict[str, Any]:
        q = self._normalized(query)

        # A. Patient identification and basic information
        if q == "find the hospital record for bobby jackson":
            return self._records(self._patient_rows())
        if q == "what is bobby jackson's age":
            return self._patient_field("age_at_admission")
        if q == "what is bobby jackson's gender":
            return self._patient_field("gender_identity")
        if q == "what is bobby jackson's blood group":
            return self._patient_field("blood_type")
        if q in {"which hospital admitted bobby jackson", "which hospital was bobby jackson admitted to"}:
            return self._patient_field("facility_name")
        if q in {"who was bobby jackson's doctor", "which doctor handled bobby jackson's recorded admission"}:
            return self._patient_field("assigned_clinician")
        if q == "what medical condition was bobby jackson admitted for":
            return self._patient_field("primary_condition")
        if q in {"show all available information about bobby jackson", "show bobby jackson's admission-to-discharge journey"}:
            rows = self._patient_rows().sort_values("admission_date")
            return self._records(rows)
        if q == "find all records for patients aged above 65":
            return self._records(self.loader.filter(age_at_admission__gt=65))
        if q == "show all patients with blood group o-negative":
            return self._records(self.loader.filter(blood_type="O-"))

        # B. Patient lifecycle and admission history
        bobby_fields = {
            "when was bobby jackson admitted": "admission_date",
            "what was bobby jackson's admission type": "admission_type",
            "when was bobby jackson discharged": "discharge_date",
            "how many days did bobby jackson stay in the hospital": "length_of_stay_days",
            "what medication was recorded for bobby jackson": "medication",
            "what was bobby jackson's recorded test result": "test_result",
            "what was bobby jackson's total bill for that admission": "billing_amount_usd",
            "which room was bobby jackson assigned to": "room_number",
            "what was bobby jackson's test result": "test_result",
            "what was bobby jackson's billing amount": "billing_amount_usd",
            "which insurance provider was recorded for bobby jackson": "payor_name",
        }
        if q in bobby_fields:
            return self._patient_field(bobby_fields[q])
        if q == "show the complete chronological admission history for records matching a given patient name":
            return self._needs_input("a patient name", "Synthetic Patient 000001")

        # C. Hospital, room and doctor
        if q == "list the patient records assigned to room 328 at northwestern memorial hospital":
            return self._records(self.loader.filter(room_number=328, facility_name="Northwestern Memorial Hospital"))
        if q == "who was the doctor assigned to room 328's recorded patient admission":
            rows = self.loader.filter(room_number=328)
            return {"status": "ok", "doctors": sorted(rows["assigned_clinician"].unique().tolist()), "record_count": len(rows)}
        if q in {"which hospital recorded the most admissions", "which hospital handled the highest number of admissions"}:
            counts = self.frame["facility_name"].value_counts()
            return {"facility": str(counts.index[0]), "admissions": int(counts.iloc[0]), "all_facilities": self._series_dict(counts)}
        if q == "how many patients were admitted to uchicago medicine":
            return {"facility": "UChicago Medicine", "admissions": int(len(self.loader.filter(facility_name="UChicago Medicine")))}
        if q == "show all records for patients treated by dr. matthew smith":
            return self._records(self.loader.filter(assigned_clinician="Dr. Matthew Smith"))
        if q == "which medical conditions were handled by a particular doctor":
            return self._needs_input("a doctor name", "Clinician-002")
        if q == "which hospital recorded the most emergency admissions":
            counts = self.loader.filter(admission_type="Emergency")["facility_name"].value_counts()
            return {"facility": str(counts.index[0]), "emergency_admissions": int(counts.iloc[0]), "all_facilities": self._series_dict(counts)}
        if q == "what was the average length of stay at each hospital":
            return {"average_stay_days": self.analytics.average_length_of_stay("facility_name")}

        # D. Admissions and discharge management
        if q == "how many admissions occurred in january 2024":
            rows = self.loader.filter(admission_date__between=("2024-01-01", "2024-01-31"))
            return {"period": "2024-01", "admissions": int(len(rows))}
        if q == "how many patients were admitted between two dates":
            return self._needs_input("a start date and end date", "2023-01-01 to 2023-12-31")
        if q == "how many emergency admissions were recorded":
            return {"emergency_admissions": int(len(self.loader.filter(admission_type="Emergency")))}
        if q == "how many elective admissions were recorded":
            return {"elective_admissions": int(len(self.loader.filter(admission_type="Elective")))}
        if q == "which admission type occurred most frequently":
            counts = self.frame["admission_type"].value_counts()
            return {"admission_type": str(counts.index[0]), "admissions": int(counts.iloc[0]), "all_types": self._series_dict(counts)}
        if q == "how many discharges occurred in february 2024":
            rows = self.loader.filter(discharge_date__between=("2024-02-01", "2024-02-29"))
            return {"period": "2024-02", "discharges": int(len(rows))}
        if q == "show the patient records discharged on a specific date":
            return self._needs_input("a discharge date", "2024-02-07")
        if q == "what was the average hospital stay for emergency admissions":
            rows = self.loader.filter(admission_type="Emergency")
            return {"average_stay_days": round(float(rows["length_of_stay_days"].mean()), 2)}
        if q == "which patients had the longest hospital stays":
            longest = self.frame["length_of_stay_days"].max()
            return self._records(self.frame.loc[self.frame["length_of_stay_days"].eq(longest)])
        if q == "which hospital recorded the highest number of discharges in 2023":
            rows = self.loader.filter(discharge_date__between=("2023-01-01", "2023-12-31"))
            counts = rows["facility_name"].value_counts()
            return {"facility": str(counts.index[0]), "discharges": int(counts.iloc[0]), "all_facilities": self._series_dict(counts)}

        # E. Medical conditions and medications
        if q == "how many admissions were recorded for diabetes":
            return {"condition": "Diabetes", "admissions": int(len(self.loader.filter(primary_condition="Diabetes")))}
        if q == "show all patient records with asthma":
            return self._records(self.loader.filter(primary_condition="Asthma"))
        if q == "which medical condition appears most frequently":
            counts = self.frame["primary_condition"].value_counts()
            return {"condition": str(counts.index[0]), "admissions": int(counts.iloc[0]), "all_conditions": self._series_dict(counts)}
        if q == "which medications were recorded for patients with diabetes":
            rows = self.loader.filter(primary_condition="Diabetes")
            return {"condition": "Diabetes", "medications": self._series_dict(rows["medication"].value_counts())}
        if q == "how many records contain an alzheimer's diagnosis" or q == "how many records contain an alzheimer’s diagnosis":
            return {"condition": "Alzheimer's", "admissions": int(len(self.loader.filter(primary_condition="Alzheimer’s")))}
        if q == "which conditions have the longest average hospital stay":
            averages = self.frame.groupby("primary_condition")["length_of_stay_days"].mean().sort_values(ascending=False)
            return {"average_stay_days": self._series_dict(averages)}
        if q == "which medications appear most frequently in the dataset":
            return {"medications": self._series_dict(self.frame["medication"].value_counts())}
        if q == "compare the average length of stay for cancer and heart disease":
            return self.analytics.compare_conditions(["Cancer", "Heart Disease"])
        if q == "which medical conditions are most common among patients aged over 60":
            rows = self.loader.filter(age_at_admission__gt=60)
            return {"conditions": self._series_dict(rows["primary_condition"].value_counts())}

        # F. Test results and patient records
        if q == "show all patient records with abnormal test results":
            return self._records(self.loader.filter(test_result="Abnormal"))
        if q == "how many test results were normal":
            return {"test_result": "Normal", "count": int(len(self.loader.filter(test_result="Normal")))}
        if q == "how many results were inconclusive":
            return {"test_result": "Inconclusive", "count": int(len(self.loader.filter(test_result="Inconclusive")))}
        if q == "which medical condition has the most abnormal results":
            rows = self.loader.filter(test_result="Abnormal")
            counts = rows["primary_condition"].value_counts()
            return {"condition": str(counts.index[0]), "abnormal_results": int(counts.iloc[0]), "all_conditions": self._series_dict(counts)}
        if q == "what percentage of diabetes records have abnormal results":
            return {"condition": "Diabetes", "abnormal_percentage": self.analytics.abnormal_result_percentage(primary_condition="Diabetes")}
        if q == "compare test-result categories across hospitals":
            table = pd.crosstab(self.frame["facility_name"], self.frame["test_result"])
            return {str(index): {str(k): int(v) for k, v in row.items()} for index, row in table.iterrows()}
        if q == "which doctors have records containing inconclusive test results":
            rows = self.loader.filter(test_result="Inconclusive")
            return {"doctors": self._series_dict(rows["assigned_clinician"].value_counts())}
        if q == "show patients who had both an emergency admission and an abnormal test result":
            return self._records(self.loader.filter(admission_type="Emergency", test_result="Abnormal"))
        if q == "what proportion of all test results were abnormal":
            return {"abnormal_test_result_percentage": self.analytics.abnormal_result_percentage()}

        # G. Billing and insurance
        if q == "show patients with bills above $50,000":
            return self._records(self.loader.filter(billing_amount_usd__gt=50000))
        if q == "what is the average billing amount per admission":
            return {"average_billing_amount_usd": round(float(self.frame["billing_amount_usd"].mean()), 2)}
        if q == "which hospital has the highest total recorded billing amount":
            totals = self.frame.groupby("facility_name")["billing_amount_usd"].sum().sort_values(ascending=False)
            return {"facility": str(totals.index[0]), "total_billing_usd": round(float(totals.iloc[0]), 2), "all_facilities": self._series_dict(totals)}
        if q == "which medical condition has the highest average billing amount":
            averages = self.frame.groupby("primary_condition")["billing_amount_usd"].mean().sort_values(ascending=False)
            return {"condition": str(averages.index[0]), "average_billing_usd": round(float(averages.iloc[0]), 2), "all_conditions": self._series_dict(averages)}
        if q == "compare the average billing amount for emergency and elective admissions":
            rows = self.loader.filter(admission_type__in=["Emergency", "Elective"])
            return {"average_billing_usd": self._series_dict(rows.groupby("admission_type")["billing_amount_usd"].mean())}
        if q == "which insurance provider appears most often":
            counts = self.frame["payor_name"].value_counts()
            return {"payor": str(counts.index[0]), "admissions": int(counts.iloc[0]), "all_payors": self._series_dict(counts)}
        if q == "what is the total billing amount associated with each insurance provider":
            totals = self.frame.groupby("payor_name")["billing_amount_usd"].sum().sort_values(ascending=False)
            return {"total_billing_usd": self._series_dict(totals)}
        if q == "show the ten admissions with the highest billing amounts":
            return self._records(self.frame.nlargest(10, "billing_amount_usd"), limit=10)

        # H. Hospital operations and analytics
        if q == "which hospital had the longest average length of stay":
            averages = self.frame.groupby("facility_name")["length_of_stay_days"].mean().sort_values(ascending=False)
            return {"facility": str(averages.index[0]), "average_stay_days": round(float(averages.iloc[0]), 2), "all_facilities": self._series_dict(averages)}
        if q == "which age group accounts for the most admissions":
            bands = pd.cut(self.frame["age_at_admission"], bins=[-1, 17, 39, 59, 79, float("inf")], labels=["0-17", "18-39", "40-59", "60-79", "80+"])
            counts = bands.value_counts().sort_values(ascending=False)
            return {"age_group": str(counts.index[0]), "admissions": int(counts.iloc[0]), "all_groups": self._series_dict(counts)}
        if q == "what percentage of patients in the records are male and female":
            percentages = self.frame["gender_identity"].value_counts(normalize=True).mul(100)
            return {"percentage": self._series_dict(percentages)}
        if q == "which month had the highest admission volume":
            counts = self.frame["admission_date"].dt.to_period("M").astype(str).value_counts().sort_values(ascending=False)
            return {"month": str(counts.index[0]), "admissions": int(counts.iloc[0])}
        if q == "how did admission numbers change between 2022 and 2023":
            counts = self.frame["admission_date"].dt.year.value_counts()
            first, second = int(counts.get(2022, 0)), int(counts.get(2023, 0))
            return {"2022": first, "2023": second, "absolute_change": second - first, "percentage_change": round(((second - first) / first * 100), 2) if first else None}
        if q == "what percentage of recorded admissions were emergencies":
            return {"emergency_percentage": round(float(self.frame["admission_type"].eq("Emergency").mean() * 100), 2)}
        if q == "which hospital recorded the highest average bill per admission":
            averages = self.frame.groupby("facility_name")["billing_amount_usd"].mean().sort_values(ascending=False)
            return {"facility": str(averages.index[0]), "average_billing_usd": round(float(averages.iloc[0]), 2), "all_facilities": self._series_dict(averages)}
        if q == "how many recorded hospital stays exceeded 30 days":
            return {"stays_over_30_days": int(self.frame["length_of_stay_days"].gt(30).sum())}
        if q == "what are the top five most frequently recorded medical conditions":
            counts = self.frame["primary_condition"].value_counts().head(5)
            return {"top_conditions": self._series_dict(counts)}

        # I. Multiple-filter questions
        filters: dict[str, dict[str, Any]] = {
            "show female patients over 60 with diabetes": {"gender_identity": "Female", "age_at_admission__gt": 60, "primary_condition": "Diabetes"},
            "find emergency admissions for patients with heart disease": {"admission_type": "Emergency", "primary_condition": "Heart Disease"},
            "show patients with abnormal test results and stays longer than 10 days": {"test_result": "Abnormal", "length_of_stay_days__gt": 10},
            "find cancer admissions at uchicago medicine during 2023": {"primary_condition": "Cancer", "facility_name": "UChicago Medicine", "admission_date__between": ("2023-01-01", "2023-12-31")},
            "show medicare-covered admissions with bills above $20,000": {"payor_name": "Medicare", "billing_amount_usd__gt": 20000},
            "find patients aged under 18 admitted for asthma": {"age_at_admission__lt": 18, "primary_condition": "Asthma"},
            "show elective admissions with stays longer than 20 days": {"admission_type": "Elective", "length_of_stay_days__gt": 20},
            "list patients with blood type ab-negative and abnormal test results": {"blood_type": "AB-", "test_result": "Abnormal"},
            "find admissions for infections that lasted more than seven days": {"primary_condition": "Infections", "length_of_stay_days__gt": 7},
            "show patients admitted in 2024 whose bills exceeded $40,000": {"admission_date__between": ("2024-01-01", "2024-12-31"), "billing_amount_usd__gt": 40000},
        }
        if q in filters:
            return self._records(self.loader.filter(**filters[q]))

        # J. Advanced, multi-agent questions
        if q == "give me a complete summary of bobby jackson's recorded hospital admission, including medical details, length of stay and billing":
            return self.ehr.patient_summary("Bobby Jackson")
        if q == "compare diabetes admissions across all four hospitals, including admission count, average stay and average bill":
            return self._facility_metrics(self.loader.filter(primary_condition="Diabetes"))
        if q == "identify historical admissions with unusually long hospital stays and unusually high bills":
            stay_cutoff = float(self.frame["length_of_stay_days"].quantile(0.95))
            bill_cutoff = float(self.frame["billing_amount_usd"].quantile(0.95))
            result = self.frame.loc[self.frame["length_of_stay_days"].ge(stay_cutoff) & self.frame["billing_amount_usd"].ge(bill_cutoff)]
            payload = self._records(result)
            payload["method"] = {"long_stay_cutoff_days_p95": stay_cutoff, "high_bill_cutoff_usd_p95": round(bill_cutoff, 2)}
            return payload
        if q == "summarize emergency admissions during 2023, including common conditions, test-result categories and total billing":
            rows = self.loader.filter(admission_type="Emergency", admission_date__between=("2023-01-01", "2023-12-31"))
            return {"admissions": int(len(rows)), "conditions": self._series_dict(rows["primary_condition"].value_counts()), "test_results": self._series_dict(rows["test_result"].value_counts()), "total_billing_usd": round(float(rows["billing_amount_usd"].sum()), 2)}
        if q == "find patients with abnormal test results and generate an administrative review summary":
            rows = self.loader.filter(test_result="Abnormal")
            return {"record_count": int(len(rows)), "human_review_required": int(rows["human_review_required"].sum()), "conditions": self._series_dict(rows["primary_condition"].value_counts()), "sample_records": self.loader.records(rows, limit=25)}
        if q == "compare admission volumes, average lengths of stay and billing amounts across all hospitals":
            return self._facility_metrics()
        if q == "generate a historical hospital utilization report for january 2024":
            rows = self.loader.filter(admission_date__between=("2024-01-01", "2024-01-31"))
            return {"period": "2024-01", "total_admissions": int(len(rows)), "facilities": self._facility_metrics(rows), "admission_types": self._series_dict(rows["admission_type"].value_counts())}
        if q == "identify admissions lasting more than 30 days and prepare a case-review list for hospital administrators":
            rows = self.loader.filter(length_of_stay_days__gt=30).sort_values("length_of_stay_days", ascending=False)
            return self._records(rows)
        if q == "analyze how billing amounts vary with admission type, medical condition and length of stay":
            return {
                "by_admission_type": self.analytics.billing_summary("admission_type"),
                "by_condition": self.analytics.billing_summary("primary_condition"),
                "billing_los_correlation": round(float(self.frame["billing_amount_usd"].corr(self.frame["length_of_stay_days"])), 4),
            }
        if q == "prepare a patient discharge summary using the recorded admission, diagnosis, medication, test-result category, discharge date and billing details":
            return self._needs_input("a patient name or patient ID", "PAT-000001")

        return {
            "status": "unsupported_local_query",
            "message": "Use ASI:One planner mode or a structured specialist method for this query.",
        }

