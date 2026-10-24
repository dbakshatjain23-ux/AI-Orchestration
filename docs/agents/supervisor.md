# CareFlow Supervisor

**One entry point for coordinated healthcare operations: find records, analyze cohorts, review recorded risks and prepare administrative reports.**

## What it does

1. **Plans:** uses ASI:One to interpret a request and coordinate six specialists.
2. **Grounds:** relies on source records and deterministic calculations for patient facts and statistics.
3. **Reviews:** asks for a human decision before executing its reviewed report and workspace tools.
4. **Reports:** returns progress, results, blocked outcomes and decision evidence while preserving the planner session.

## Try it

- “Find patients with abnormal results and stays longer than 30 days. Analyze the cohort and ask before generating an administrative review package.”
- “Retrieve PAT-000007, check eligibility for a mock Gmail draft and ask before running the workspace demo. Do not send email.”
- When an action is pending, reply **approve** or **deny**.

## Who it's for

Hospital operations teams and reviewers exploring coordinated workflows over synthetic healthcare data.

## Details

- **Works with:** EHR Search, Math & Analytics, Administrative Triage, Document Generator, Workspace Sync, and Compliance & Audit.
- **Protocol:** Agent Chat Protocol. Live planning needs an ASI API key and reachable specialist addresses.
- **Safety:** approval cannot override missing consent or unresolved record review. The integrated workspace flow is mock-only.
- **Scope:** administrative demonstration using synthetic data; no diagnosis, treatment or emergency dispatch. Offline demos use a scripted planner.
- **Source:** [supervisor_agent.py](https://github.com/dbakshatjain23-ux/AI-Orchestration/blob/codex/dev4-supervisor-integration/agents/supervisor_agent.py).

Part of the seven-agent **CareFlow** system.
