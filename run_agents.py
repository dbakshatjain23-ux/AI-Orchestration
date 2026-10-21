"""Launch the supervisor and all six specialists as isolated local processes."""

from __future__ import annotations

import argparse
import multiprocessing as mp
import signal
from collections.abc import Callable


def run_supervisor() -> None:
    from agents.supervisor_agent import build_uagent
    build_uagent().run()


def run_ehr() -> None:
    from agents.agent_1_ehr_search import build_uagent
    build_uagent().run()


def run_analytics() -> None:
    from agents.agent_2_math_analytics import build_uagent
    build_uagent().run()


def run_triage() -> None:
    from agents.agent_3_clinical_triage import build_uagent
    build_uagent().run()


def run_documents() -> None:
    from agents.agent_4_doc_generator import build_uagent
    build_uagent().run()


def run_workspace() -> None:
    from agents.agent_5_workspace_sync import build_uagent
    build_uagent().run()


def run_compliance() -> None:
    from agents.agent_6_compliance_audit import build_uagent
    build_uagent().run()


RUNNERS: dict[str, Callable[[], None]] = {
    "supervisor": run_supervisor,
    "ehr": run_ehr,
    "analytics": run_analytics,
    "triage": run_triage,
    "documents": run_documents,
    "workspace": run_workspace,
    "compliance": run_compliance,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="+",
        choices=RUNNERS,
        default=list(RUNNERS),
        help="Optional subset of services to start",
    )
    args = parser.parse_args()
    processes = [mp.Process(name=name, target=RUNNERS[name]) for name in args.only]
    for process in processes:
        process.start()
    print("Started: " + ", ".join(f"{p.name} (pid={p.pid})" for p in processes), flush=True)
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=5)


if __name__ == "__main__":
    mp.freeze_support()
    signal.signal(signal.SIGINT, signal.default_int_handler)
    main()
