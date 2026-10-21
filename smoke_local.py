"""Start all uAgents, verify every local port, then shut them down."""

from __future__ import annotations

import json
import multiprocessing as mp
import socket
import time

from config import settings
from run_agents import RUNNERS


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def main() -> None:
    ports = [settings.supervisor_port, *settings.agent_ports]
    processes = [mp.Process(name=name, target=runner) for name, runner in RUNNERS.items()]
    for process in processes:
        process.start()
    deadline = time.monotonic() + 60
    ready: set[int] = set()
    try:
        while time.monotonic() < deadline:
            failed = [
                process for process in processes
                if process.exitcode is not None and process.exitcode != 0
            ]
            if failed:
                raise RuntimeError(
                    "Agent process exited early: "
                    + ", ".join(f"{process.name}={process.exitcode}" for process in failed)
                )
            ready.update(port for port in ports if port_is_open(port))
            if len(ready) == len(ports):
                break
            time.sleep(0.25)
        missing = sorted(set(ports) - ready)
        if missing:
            raise RuntimeError(f"Timed out waiting for local agent ports: {missing}")
        print(json.dumps({
            "status": "ok",
            "agents": len(processes),
            "ports": sorted(ready),
            "external_actions_executed": False,
        }))
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=5)


if __name__ == "__main__":
    mp.freeze_support()
    main()
