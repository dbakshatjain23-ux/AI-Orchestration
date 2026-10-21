# CareFlow Agentverse Deployment

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

This repository supports two runtime modes without changing business logic:

- Local HTTP mode: all seven ports through `run_agents.py`.
- Agentverse mailbox mode: one long-running role through `deploy_agent.py`.

Mailbox mode is the recommended first deployment path for this repository because
the shared dataset and Python dependencies remain in a normal Python runtime while
Agentverse supplies identity, discovery, message delivery, and ASI:One access.

## 1. Redeem the hackathon access

Redeem `FETCHATHONIND` for ASI:One Pro and Agentverse Premium, then create:

- an ASI:One API key;
- an Agentverse API key;
- one stable, high-entropy base `AGENT_SEED` kept outside Git.

An agent address is derived from the seed plus the role name. Reusing the same base
seed across deployments keeps all seven addresses stable; exposing it allows an
attacker to impersonate every CareFlow agent.

## 2. Common deployment environment

```dotenv
AGENT_MAILBOX=true
AGENT_CONCURRENT_MESSAGES=true
AGENT_SEED=<stable secret>
ASI_ONE_API_KEY=<ASI:One API key>
ASI_ONE_MODEL=asi1
ASI_ONE_BASE_URL=https://api.asi1.ai/v1
ENABLE_INTERACTIVE_CARDS=true
ENABLE_GOOGLE_ACTIONS=false
DATASET_PATH=docs/sample_dataset.csv
OUTPUT_DIR=output
```

Do not configure Google credentials for the hackathon deployment.

## 3. Start and register specialists first

Run one role at a time during registration:

```powershell
$env:AGENT_MAILBOX = "true"
$env:AGENT_ROLE = "ehr"
.\.venv\Scripts\python.exe deploy_agent.py
```

Open the Inspector URL printed by the process, connect it to Agentverse using
Mailbox, complete the profile with the matching entry from
`deploy/agentverse_profiles.json`, and record its `agent1q...` address.

Repeat in this order:

1. `ehr`
2. `analytics`
3. `triage`
4. `documents`
5. `workspace`
6. `compliance`

For a persistent cloud worker, use the same repository and command:

```text
python deploy_agent.py --agent <role>
```

The process needs outbound HTTPS access and must remain running to collect mailbox
messages. It does not need a public inbound port.

## 4. Configure the Supervisor

Add the six recorded addresses to the Supervisor worker only:

```dotenv
AGENT1_ADDRESS=agent1q...
AGENT2_ADDRESS=agent1q...
AGENT3_ADDRESS=agent1q...
AGENT4_ADDRESS=agent1q...
AGENT5_ADDRESS=agent1q...
AGENT6_ADDRESS=agent1q...
AGENT_ROLE=supervisor
```

Then start and register it:

```powershell
.\.venv\Scripts\python.exe deploy_agent.py
```

## 5. ASI:One acceptance flow

Directly mention the Supervisor in ASI:One and send:

> Find patients with abnormal results and stays longer than 30 days. Use the
> specialist agents to analyze and prioritize the cohort, then prepare an audited
> administrative review package with at most 10 detailed cases. Do not contact
> patients or use Google Workspace.

Acceptance criteria:

1. ASI:One shows a multi-step plan and specialist progress.
2. EHR, analytics, triage, document, and compliance capabilities are visible in the trace.
3. The Supervisor proposes `finalize_administrative_review` rather than silently executing it.
4. ASI:One renders a native Review card with Approve and Deny actions.
5. Deny returns a safe cancellation using the same planner session.
6. Approve generates the grounded report, appends an audit event, and resumes ASI:One.
7. The final response identifies source facts, agents used, generated outcome, and required human follow-up.

## 6. Submission evidence

Capture and publish:

- Supervisor and specialist Agentverse profile URLs;
- all seven stable addresses in the public README (never the seed);
- an ASI:One shared-chat URL showing the full workflow;
- screenshots of the live plan and approval card;
- a 3–5 minute demo video;
- the exact Git commit used for the deployment.
