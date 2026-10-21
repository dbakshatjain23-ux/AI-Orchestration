"""Start exactly one CareFlow agent for Agentverse mailbox/cloud deployment."""

from __future__ import annotations

import argparse
import os

from run_agents import RUNNERS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent",
        choices=RUNNERS,
        default=os.getenv("AGENT_ROLE", "").strip() or None,
        help="Agent role; defaults to the AGENT_ROLE environment variable",
    )
    args = parser.parse_args()
    if not args.agent:
        parser.error("set --agent or AGENT_ROLE")
    if os.getenv("AGENT_MAILBOX", "").strip().casefold() not in {
        "1", "true", "yes", "on"
    } and not os.getenv("AGENT_ENDPOINT", "").strip():
        parser.error(
            "deployment requires AGENT_MAILBOX=true or a public AGENT_ENDPOINT"
        )
    print(f"Starting CareFlow deployment role: {args.agent}", flush=True)
    RUNNERS[args.agent]()


if __name__ == "__main__":
    main()
