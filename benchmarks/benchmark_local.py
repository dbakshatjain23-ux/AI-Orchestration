"""Repeatable local performance budgets for deterministic orchestration paths."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from agents.agent_1_ehr_search import EHRSearchAgent
from config import settings
from services.workflow_orchestrator import WorkflowOrchestrator
from utils.dataset_loader import DatasetLoader


BUDGETS_SECONDS = {
    "cached_load_s": 2.5,
    "exact_200_first_s": 4.5,
    "exact_200_hot_s": 3.5,
    "advanced_flow_s": 1.5,
}


def timed(callable_):
    started = time.perf_counter()
    value = callable_()
    return value, time.perf_counter() - started


def run_once() -> dict[str, float | int]:
    loader, cached_load = timed(lambda: _loaded_dataset())
    ehr = EHRSearchAgent(loader)
    _, first_lookups = timed(lambda: [
        ehr.find_patient_by_id(f"PAT-{index:06d}") for index in range(1, 201)
    ])
    _, hot_lookups = timed(lambda: [
        ehr.find_patient_by_id(f"PAT-{index:06d}") for index in range(1, 201)
    ])
    orchestrator = WorkflowOrchestrator(loader)
    result, advanced_flow = timed(lambda: orchestrator.prepare_advanced_review(
        minimum_days=30,
        prepare_outreach=False,
        max_pdf_cases=1,
    ))
    return {
        "rows": loader.row_count,
        "advanced_matches": result.summary["matching_records"],
        "cached_load_s": cached_load,
        "exact_200_first_s": first_lookups,
        "exact_200_hot_s": hot_lookups,
        "advanced_flow_s": advanced_flow,
    }


def _loaded_dataset() -> DatasetLoader:
    loader = DatasetLoader(
        settings.dataset_path, settings.sqlite_path, settings.parquet_path
    )
    loader.row_count
    return loader


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--assert-budget", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be between 1 and 10")
    samples = [run_once() for _ in range(args.runs)]
    metrics = {
        key: round(statistics.median(float(sample[key]) for sample in samples), 4)
        for key in BUDGETS_SECONDS
    }
    result = {
        "runs": args.runs,
        "rows": samples[-1]["rows"],
        "advanced_matches": samples[-1]["advanced_matches"],
        "median_seconds": metrics,
        "budgets_seconds": BUDGETS_SECONDS,
        "budget_status": {
            key: "pass" if metrics[key] <= budget else "fail"
            for key, budget in BUDGETS_SECONDS.items()
        },
    }
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.assert_budget and "fail" in result["budget_status"].values():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
