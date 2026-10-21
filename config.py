"""Central configuration for the healthcare orchestration demo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # Keep local deterministic tools usable before full install.
    def load_dotenv(*_args, **_kwargs):
        return False


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


def _agent_addresses() -> tuple[str, ...]:
    return tuple(
        value
        for index in range(1, 7)
        if (value := os.getenv(f"AGENT{index}_ADDRESS", "").strip())
    )


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    dataset_path: Path = ROOT_DIR / "docs" / "sample_dataset.csv"
    output_dir: Path = ROOT_DIR / "output"
    sqlite_path: Path = ROOT_DIR / "output" / "healthcare.sqlite"
    parquet_path: Path = ROOT_DIR / "output" / "healthcare.parquet"
    asi_one_api_key: str = os.getenv("ASI_ONE_API_KEY", "")
    asi_one_model: str = os.getenv("ASI_ONE_MODEL", "asi1")
    asi_one_base_url: str = os.getenv(
        "ASI_ONE_BASE_URL", "https://api.asi1.ai/v1"
    ).rstrip("/")
    google_service_account_file: str = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_FILE", ""
    )
    google_delegated_user: str = os.getenv("GOOGLE_DELEGATED_USER", "")
    agent_seed: str = os.getenv("AGENT_SEED", "")
    time_zone: str = os.getenv("TIME_ZONE", "Asia/Kolkata")
    agent_public_base_url: str = os.getenv("AGENT_PUBLIC_BASE_URL", "").rstrip("/")
    supervisor_port: int = _int_env("SUPERVISOR_PORT", 8000)
    max_external_concurrency: int = _int_env("MAX_EXTERNAL_CONCURRENCY", 4)
    agent_ports: tuple[int, ...] = tuple(
        _int_env(f"AGENT{index}_PORT", 8000 + index) for index in range(1, 7)
    )
    specialist_addresses: tuple[str, ...] = _agent_addresses()

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir


def agent_runtime_kwargs(name: str, slot: int) -> dict[str, object]:
    """Return collision-free local runtime settings for one uAgent.

    Slot 0 is the supervisor and slots 1-6 are specialists. A public endpoint is
    advertised only when explicitly configured because localhost is not reachable
    from Agentverse.
    """

    port = settings.supervisor_port if slot == 0 else settings.agent_ports[slot - 1]
    descriptions = {
        0: "Supervisor for stateful healthcare operations planning, specialist orchestration, HITL approval, and audited execution.",
        1: "Deterministic EHR search across patient demographics, encounters, facilities, conditions, rooms, clinicians, and dates.",
        2: "Deterministic healthcare analytics for averages, percentages, comparisons, admission volumes, billing summaries, and rankings.",
        3: "Administrative clinical triage reporting recorded acuity, human-review, and L2 escalation fields without diagnosing.",
        4: "PDF generator for discharge summaries, accounting invoices, and long-stay administrative case reviews.",
        5: "Google Workspace action preparation for Gmail, Calendar, and Sheets with supervisor-controlled execution approval.",
        6: "Patient communication consent, guardian checks, and append-only compliance workflow audit logging.",
    }
    kwargs: dict[str, object] = {
        "name": name,
        "port": port,
        "description": descriptions[slot],
        "readme_path": str(ROOT_DIR / "README.md"),
        "metadata": {"domain": "healthcare-operations", "agent_slot": slot},
    }
    if settings.agent_seed:
        kwargs["seed"] = f"{settings.agent_seed}:{name}"
    if settings.agent_public_base_url:
        kwargs["endpoint"] = [f"{settings.agent_public_base_url}/{name}/submit"]
    return kwargs


settings = Settings()

