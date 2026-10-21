# Healthcare Agent Orchestration System

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**CareFlow** is an AI hospital-operations supervisor that turns a natural-language
goal into a grounded, auditable multi-agent workflow inside ASI:One.

This repository implements the complete supervisor-led flow in `docs/user_flow.md`. A clinician or administrator talks to the Supervisor through Agent Chat Protocol; the Supervisor opens a stateful ASI:One planner session, exposes six narrow specialist agents, streams plan progress, pauses external actions for human approval, rechecks consent, executes approved Google Workspace actions, and records an append-only audit event.

The 100-question catalogue is a regression suite for data coverage. It is not the application architecture or the primary runtime.

## Where AI is used

ASI:One is the reasoning layer: it interprets an open-ended objective, builds and
adapts a plan, selects specialist agents, streams progress, synthesizes grounded
results, and proposes tool calls. Exact retrieval, calculations, recorded triage
fields, consent enforcement, PDF generation, and auditing remain deterministic.
This separation prevents the LLM from inventing patient facts or overriding safety
controls.

The local CLI workflows deliberately bypass the LLM so they can be tested without
network credentials. A live ASI:One demonstration requires the registered specialist
addresses and exercises the AI planner path.

## Runtime architecture

| Service | Local port | Responsibility |
| --- | ---: | --- |
| Supervisor | 8000 | ASI:One planning, progress, session continuity, tool calls, HITL |
| EHR Search | 8001 | Exact patient and multi-field record retrieval |
| Math & Analytics | 8002 | Deterministic averages, percentages, group totals, rankings |
| Clinical Triage | 8003 | Reports recorded acuity, review, and L2 escalation fields |
| Document Generator | 8004 | Discharge summaries, invoices, administrative review PDFs |
| Workspace Sync | 8005 | Prepares Gmail, Calendar, and Sheets actions; never self-approves |
| Compliance & Audit | 8006 | Consent/guardian checks and append-only JSONL audit events |

The Supervisor also exposes an approval-gated
`finalize_administrative_review` tool. It creates an abnormal-result/long-stay PDF
package and audit evidence without requiring Google Workspace. ASI:One Interactive
Cards provide native Approve/Deny controls and a terminal outcome view.

Every service publishes the Agent Chat Protocol 0.3.0 manifest. Specialist agents accept both planner-friendly plain text and canonical structured JSON. The source CSV remains read-only; `main.py --build-index` creates an indexed SQLite copy plus a source-fingerprinted Parquet cache. Agents prefer the Parquet cache for fast startup and automatically fall back when it is missing or stale.

## Setup

```powershell
C:\Users\jaksh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Required for live planning:

- `ASI_ONE_API_KEY`
- A stable, secret `AGENT_SEED`
- `AGENT1_ADDRESS` through `AGENT6_ADDRESS` after the specialists are deployed or registered

For Agentverse mailbox deployment set `AGENT_MAILBOX=true` and start one role with
`python deploy_agent.py --agent <role>`. See
[`docs/agentverse_deployment.md`](docs/agentverse_deployment.md) for the complete
specialist-first registration sequence.

Required for Google Workspace execution:

- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `GOOGLE_DELEGATED_USER` for Gmail service-account sending
- Google resources shared with the service account and the scopes described in `docs/apis_integrations.md`

Set `AGENT_PUBLIC_BASE_URL` only when a public reverse proxy routes each `/<agent-name>/submit` endpoint to its corresponding local port. Localhost agents intentionally skip public registration.

## Run the complete system

Build the optional SQLite index:

```powershell
.\.venv\Scripts\python.exe main.py --build-index
```

Start all seven uAgents:

```powershell
.\.venv\Scripts\python.exe run_agents.py
```

Run a bounded local startup smoke test without ASI:One or Google credentials:

```powershell
.\.venv\Scripts\python.exe smoke_local.py
```

Or start a subset:

```powershell
.\.venv\Scripts\python.exe run_agents.py --only supervisor ehr analytics
```

Once deployed, put the six specialist `agent1q...` addresses in `.env`, start/deploy the Supervisor, then @mention it in ASI:One Chat. A representative full-flow prompt is:

> Find patients with abnormal results and stays longer than 30 days. Use the specialist agents to analyze and prioritize the cohort, then prepare an audited administrative review package with at most 10 detailed cases. Do not contact patients or use Google Workspace.

The planner may call specialists immediately, but durable report creation and optional
Gmail, Calendar, and Sheets calls return to the Supervisor as tools. The Supervisor
shows an ASI:One Review card, resumes with the same `x-session-id`, and records the
decision and result. Google actions are hidden and blocked unless
`ENABLE_GOOGLE_ACTIONS=true`.

## Deterministic local verification

Run the same advanced flow without an LLM or external dispatch:

```powershell
.\.venv\Scripts\python.exe workflow.py advanced-review --minimum-days 30 --no-outreach
.\.venv\Scripts\python.exe workflow.py advanced-review --minimum-days 30 --spreadsheet-id YOUR_SHEET_ID
```

The second command only prepares Sheets and consent-eligible Gmail actions. It does not execute them. `WorkflowOrchestrator.execute_approved_actions(..., approved=True)` is the explicit execution boundary and rechecks consent and recipient identity immediately before Gmail dispatch.

For large cohorts, every matching row is counted, triaged, and included in a prepared Sheets queue. PDF detail and individual outreach actions default to 100 each to avoid accidental bulk disclosure or dispatch; use `--max-pdf-cases` and `--max-outreach-actions` to set deliberate limits. The result always reports whether either set was truncated.

Other local commands:

```powershell
.\.venv\Scripts\python.exe main.py "What proportion of all test results were abnormal?"
.\.venv\Scripts\python.exe workflow.py discharge PAT-000001
.\.venv\Scripts\python.exe workflow.py long-stay-review --minimum-days 30
```

## Safety and failure behavior

- No diagnosis or inferred clinical threshold: triage reports fields already recorded in the dataset.
- Email is blocked when contact/email consent is missing, guardian review is required, the patient is under 18, the patient is absent, or the recipient differs from the recorded patient email.
- External actions require explicit human approval and produce an audit event whether approved, denied, blocked, or failed.
- ASI:One tool results are appended in required message order and sent with the original session ID.
- Missing records and incomplete requests return structured `not_found` or `needs_input` responses instead of fabricated data.
- Network, specialist, or API failures are returned as structured errors and do not silently count as success.

## Performance and parallelism

- Independent approved tools run concurrently through a bounded supervisor semaphore. `MAX_EXTERNAL_CONCURRENCY` defaults to 4.
- Local prepared-action batches use an ordered bounded thread pool and keep audit writes serialized.
- Triage and PDF preparation overlap, PDF dependencies warm during agent startup, and large cohorts use vectorized escalation counts.
- Patient exact-match indexes are built lazily and reused.
- Cache writes are atomic; cache fingerprints include source path, timestamp, and size.
- Large-cohort output limits remain explicit and do not alter total counts.

Run the three-pass median performance budget:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.benchmark_local --runs 3 --assert-budget
```

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite covers CSV validation, SQLite and Parquet materialization, natural-language specialist routing, deterministic analytics, PDFs, concurrent execution, the complete advanced workflow, approval denial, consent blocking, planner session continuity, and all 100 catalogue prompts.
