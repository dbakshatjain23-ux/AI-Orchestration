"""Validated, read-only access to the synthetic encounter dataset."""

from __future__ import annotations

from functools import cached_property
from contextlib import closing
from collections import defaultdict
import json
from pathlib import Path
import sqlite3
import os
import tempfile
from threading import RLock
from typing import Any, Iterable

import pandas as pd


REQUIRED_COLUMNS = {
    "record_id",
    "patient_id",
    "patient_full_name",
    "date_of_birth",
    "age_at_admission",
    "gender_identity",
    "blood_type",
    "contact_allowed",
    "sms_consent",
    "email_consent",
    "consent_status",
    "primary_condition",
    "clinical_priority",
    "acuity_score",
    "encounter_id",
    "admission_date",
    "discharge_date",
    "length_of_stay_days",
    "admission_type",
    "room_number",
    "facility_name",
    "assigned_clinician",
    "payor_name",
    "billing_amount_usd",
    "medication",
    "test_result",
    "human_review_required",
    "escalation_required",
    "synthetic_data_flag",
}


class DatasetValidationError(ValueError):
    """Raised when the source dataset does not meet the application contract."""


class DatasetLoader:
    """Loads the CSV once and exposes non-mutating query helpers."""

    def __init__(
        self,
        path: str | Path,
        sqlite_path: str | Path | None = None,
        parquet_path: str | Path | None = None,
    ):
        self.path = Path(path)
        self.sqlite_path = Path(sqlite_path) if sqlite_path else None
        self.parquet_path = Path(parquet_path) if parquet_path else None
        self._index_lock = RLock()

    @cached_property
    def frame(self) -> pd.DataFrame:
        if not self.path.exists():
            raise FileNotFoundError(f"Dataset not found: {self.path}")

        frame = self._read_fresh_parquet_cache()
        loaded_from_cache = frame is not None
        if frame is None:
            frame = self._read_fresh_sqlite_cache()
            loaded_from_cache = frame is not None
        if frame is None:
            frame = pd.read_csv(
                self.path,
                low_memory=False,
                dtype={
                    "record_id": "string",
                    "patient_id": "string",
                    "patient_full_name": "string",
                    "patient_phone": "string",
                    "patient_email": "string",
                    "emergency_contact_phone": "string",
                    "postal_code": "string",
                },
            )
        missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
        if missing:
            raise DatasetValidationError(
                "Dataset is missing required columns: " + ", ".join(missing)
            )

        identifier_columns = ("record_id", "patient_id", "encounter_id")
        for column in identifier_columns:
            if frame[column].isna().any() or frame[column].astype("string").str.strip().eq("").any():
                raise DatasetValidationError(f"{column} contains missing or blank values")

        numeric_columns = (
            "age_at_admission", "acuity_score", "length_of_stay_days", "billing_amount_usd"
        )
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if frame[column].isna().any():
                raise DatasetValidationError(f"{column} contains non-numeric values")
        if not frame["age_at_admission"].between(0, 130).all():
            raise DatasetValidationError("age_at_admission must be between 0 and 130")
        if not frame["acuity_score"].between(1, 5).all():
            raise DatasetValidationError("acuity_score must be between 1 and 5")
        if (frame[["length_of_stay_days", "billing_amount_usd"]] < 0).any().any():
            raise DatasetValidationError("length of stay and billing amount cannot be negative")

        for column in (
            "contact_allowed", "sms_consent", "email_consent",
            "human_review_required", "escalation_required", "synthetic_data_flag",
        ):
            frame[column] = self._coerce_boolean(frame[column], column)

        for column in ("admission_date", "discharge_date"):
            frame[column] = pd.to_datetime(
                frame[column],
                format="%Y-%m-%d" if loaded_from_cache else "%d-%m-%Y",
                errors="coerce",
            )
        if frame[["admission_date", "discharge_date"]].isna().any().any():
            raise DatasetValidationError("Admission or discharge dates are invalid")

        expected_los = (frame["discharge_date"] - frame["admission_date"]).dt.days
        mismatched = frame["length_of_stay_days"].ne(expected_los)
        if mismatched.any():
            raise DatasetValidationError(
                f"{int(mismatched.sum())} rows have inconsistent length of stay"
            )

        duplicated = frame["record_id"].duplicated(keep=False)
        if duplicated.any():
            raise DatasetValidationError(
                f"{int(duplicated.sum())} rows share duplicate record_id values"
            )
        return frame

    def _read_fresh_parquet_cache(self) -> pd.DataFrame | None:
        if self.parquet_path is None or not self.parquet_path.exists():
            return None
        metadata_path = self.parquet_path.with_suffix(self.parquet_path.suffix + ".json")
        if not metadata_path.exists():
            return None
        source = self.path.stat()
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            expected = {
                "source_path": str(self.path.resolve()),
                "source_mtime_ns": source.st_mtime_ns,
                "source_size": source.st_size,
            }
            if any(metadata.get(key) != value for key, value in expected.items()):
                return None
            return pd.read_parquet(self.parquet_path)
        except (OSError, ValueError, ImportError):
            return None

    def _read_fresh_sqlite_cache(self) -> pd.DataFrame | None:
        if self.sqlite_path is None or not self.sqlite_path.exists():
            return None
        source = self.path.stat()
        try:
            with closing(sqlite3.connect(self.sqlite_path)) as connection:
                metadata = connection.execute(
                    "SELECT source_path, source_mtime_ns, source_size FROM dataset_metadata LIMIT 1"
                ).fetchone()
                if metadata != (str(self.path.resolve()), source.st_mtime_ns, source.st_size):
                    return None
                return pd.read_sql_query("SELECT * FROM encounters", connection)
        except (sqlite3.Error, pd.errors.DatabaseError):
            return None

    @staticmethod
    def _coerce_boolean(series: pd.Series, column: str) -> pd.Series:
        if pd.api.types.is_bool_dtype(series):
            return series.astype(bool)
        mapping = {
            "true": True, "1": True, "yes": True,
            "false": False, "0": False, "no": False,
        }
        converted = series.astype("string").str.strip().str.casefold().map(mapping)
        if converted.isna().any():
            raise DatasetValidationError(f"{column} contains invalid boolean values")
        return converted.astype(bool)

    def records(self, frame: pd.DataFrame, limit: int = 100) -> list[dict[str, Any]]:
        safe = frame.head(limit).copy()
        for column in ("admission_date", "discharge_date"):
            if column in safe:
                safe[column] = safe[column].dt.strftime("%Y-%m-%d")
        return safe.where(safe.notna(), None).to_dict(orient="records")

    @cached_property
    def _exact_text_indexes(self) -> dict[str, dict[str, list[int]]]:
        return {}

    def _text_index(self, column: str) -> dict[str, list[int]]:
        """Build a normalized exact-match index lazily for repeated lookups."""

        with self._index_lock:
            existing = self._exact_text_indexes.get(column)
            if existing is not None:
                return existing
            index: defaultdict[str, list[int]] = defaultdict(list)
            for position, value in enumerate(self.frame[column].array):
                if pd.notna(value):
                    index[str(value).casefold()].append(position)
            built = dict(index)
            self._exact_text_indexes[column] = built
            return built

    def build_sqlite_index(self, destination: str | Path) -> Path:
        """Materialize a query-only SQLite copy without modifying the source CSV."""

        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        export = self.frame.copy()
        for column in ("admission_date", "discharge_date"):
            export[column] = export[column].dt.strftime("%Y-%m-%d")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            with closing(sqlite3.connect(temporary_path)) as connection:
                export.to_sql("encounters", connection, if_exists="replace", index=False)
                for column in (
                    "record_id",
                    "patient_id",
                    "patient_full_name",
                    "encounter_id",
                    "facility_name",
                    "primary_condition",
                    "admission_date",
                ):
                    connection.execute(
                        f'CREATE INDEX IF NOT EXISTS "idx_encounters_{column}" '
                        f'ON encounters("{column}")'
                    )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS dataset_metadata "
                    "(source_path TEXT, row_count INTEGER, column_count INTEGER, "
                    "source_mtime_ns INTEGER, source_size INTEGER)"
                )
                connection.execute("DELETE FROM dataset_metadata")
                connection.execute(
                    "INSERT INTO dataset_metadata VALUES (?, ?, ?, ?, ?)",
                    (
                        str(self.path.resolve()), len(export), len(export.columns),
                        self.path.stat().st_mtime_ns, self.path.stat().st_size,
                    ),
                )
                connection.commit()
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return path

    def build_parquet_cache(self, destination: str | Path) -> Path:
        """Build an atomic, non-executable columnar cache for fast local startup."""

        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        export = self.frame.copy()
        for column in ("admission_date", "discharge_date"):
            export[column] = export[column].dt.strftime("%Y-%m-%d")
        temporary_path = path.with_name(f".{path.name}-{os.getpid()}.tmp")
        metadata_path = path.with_suffix(path.suffix + ".json")
        temporary_metadata = metadata_path.with_name(
            f".{metadata_path.name}-{os.getpid()}.tmp"
        )
        source = self.path.stat()
        metadata = {
            "source_path": str(self.path.resolve()),
            "source_mtime_ns": source.st_mtime_ns,
            "source_size": source.st_size,
            "row_count": len(export),
            "column_count": len(export.columns),
        }
        try:
            export.to_parquet(temporary_path, index=False, engine="pyarrow")
            temporary_metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            os.replace(temporary_path, path)
            os.replace(temporary_metadata, metadata_path)
        finally:
            temporary_path.unlink(missing_ok=True)
            temporary_metadata.unlink(missing_ok=True)
        return path

    @property
    def row_count(self) -> int:
        return len(self.frame)

    def exact_match(self, column: str, value: Any) -> pd.DataFrame:
        self._require_columns([column])
        series = self.frame[column]
        if isinstance(value, str):
            positions = self._text_index(column).get(value.casefold(), [])
            # Fancy-position indexing already returns an independent frame.
            return self.frame.iloc[positions]
        else:
            mask = series.eq(value)
        return self.frame.loc[mask].copy()

    def filter(self, **criteria: Any) -> pd.DataFrame:
        """Filter by exact fields plus supported range suffixes.

        Supported suffixes are ``__gt``, ``__gte``, ``__lt``, ``__lte``,
        ``__contains``, ``__in``, and ``__between``.
        """

        result = self.frame
        for expression, value in criteria.items():
            column, separator, operation = expression.partition("__")
            self._require_columns([column])
            series = result[column]
            operation = operation if separator else "eq"
            if operation == "eq":
                mask = self._equality_mask(series, value)
            elif operation == "contains":
                mask = series.astype("string").str.contains(
                    str(value), case=False, regex=False, na=False
                )
            elif operation == "in":
                values = list(value) if isinstance(value, Iterable) else [value]
                if series.dtype.name in {"string", "object", "str"}:
                    folded = {str(item).casefold() for item in values}
                    mask = series.astype("string").str.casefold().isin(folded)
                else:
                    mask = series.isin(values)
            elif operation == "between":
                start, end = value
                if pd.api.types.is_datetime64_any_dtype(series):
                    start, end = pd.Timestamp(start), pd.Timestamp(end)
                mask = series.between(start, end, inclusive="both")
            elif operation in {"gt", "gte", "lt", "lte"}:
                comparator = {
                    "gt": series.gt,
                    "gte": series.ge,
                    "lt": series.lt,
                    "lte": series.le,
                }[operation]
                mask = comparator(value)
            else:
                raise ValueError(f"Unsupported filter operation: {operation}")
            result = result.loc[mask]
        return result.copy()

    @staticmethod
    def _equality_mask(series: pd.Series, value: Any) -> pd.Series:
        if isinstance(value, str):
            return series.astype("string").str.casefold().eq(value.casefold())
        return series.eq(value)

    def _require_columns(self, columns: Iterable[str]) -> None:
        missing = [column for column in columns if column not in self.frame.columns]
        if missing:
            raise KeyError("Unknown dataset columns: " + ", ".join(missing))

