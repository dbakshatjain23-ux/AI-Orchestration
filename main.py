"""Command-line entry point for local deterministic queries and planner mode."""

from __future__ import annotations

import argparse
import json

from agents.supervisor_agent import SupervisorService
from config import settings
from utils.dataset_loader import DatasetLoader


def main() -> None:
    parser = argparse.ArgumentParser(description="Healthcare agent orchestration demo")
    parser.add_argument("query", nargs="?", help="Plain-English healthcare operations question")
    parser.add_argument(
        "--planner", action="store_true", help="Use ASI:One planner mode instead of local routing"
    )
    parser.add_argument(
        "--build-index",
        action="store_true",
        help="Build output/healthcare.sqlite from the validated source CSV",
    )
    args = parser.parse_args()
    if args.build_index:
        loader = DatasetLoader(settings.dataset_path)
        sqlite_path = loader.build_sqlite_index(settings.sqlite_path)
        parquet_path = loader.build_parquet_cache(settings.parquet_path)
        print(json.dumps({
            "status": "indexed",
            "sqlite_path": str(sqlite_path),
            "parquet_path": str(parquet_path),
        }))
        return
    if not args.query:
        parser.error("query is required unless --build-index is used")
    supervisor = SupervisorService()
    if args.planner:
        for event in supervisor.stream_planner(args.query):
            print(json.dumps(event, default=str))
    else:
        print(json.dumps(supervisor.handle_local(args.query), indent=2, default=str))


if __name__ == "__main__":
    main()

