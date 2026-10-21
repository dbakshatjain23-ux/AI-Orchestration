"""CLI for multi-step administrative workflows."""

from __future__ import annotations

import argparse
import json

from services.workflow_orchestrator import WorkflowOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare healthcare administrative workflows")
    subparsers = parser.add_subparsers(dest="workflow", required=True)

    discharge = subparsers.add_parser("discharge")
    discharge.add_argument("patient_id")

    review = subparsers.add_parser("long-stay-review")
    review.add_argument("--minimum-days", type=int, default=30)
    review.add_argument("--spreadsheet-id")

    advanced = subparsers.add_parser("advanced-review")
    advanced.add_argument("--minimum-days", type=int, default=30)
    advanced.add_argument("--spreadsheet-id")
    advanced.add_argument("--no-outreach", action="store_true")
    advanced.add_argument("--max-pdf-cases", type=int, default=100)
    advanced.add_argument("--max-outreach-actions", type=int, default=100)

    args = parser.parse_args()
    orchestrator = WorkflowOrchestrator()
    if args.workflow == "discharge":
        result = orchestrator.prepare_discharge_workflow(args.patient_id)
    elif args.workflow == "long-stay-review":
        result = orchestrator.prepare_long_stay_review(
            minimum_days=args.minimum_days,
            spreadsheet_id=args.spreadsheet_id,
        )
    else:
        result = orchestrator.prepare_advanced_review(
            minimum_days=args.minimum_days,
            spreadsheet_id=args.spreadsheet_id,
            prepare_outreach=not args.no_outreach,
            max_pdf_cases=args.max_pdf_cases,
            max_outreach_actions=args.max_outreach_actions,
        )
    print(json.dumps(result.as_dict(), indent=2, default=str))


if __name__ == "__main__":
    main()

