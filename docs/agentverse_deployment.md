# CareFlow Agentverse Deployment

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

This repository supports two runtime modes without changing business logic:

- Local HTTP mode: all seven ports through `run_agents.py`.
- Agentverse mailbox mode: one role through `deploy_agent.py`, or the complete
  long-running stack through `run_agents.py`.

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

Stopping the command makes that Mailbox agent inactive. Registration is not
lost: restart the same role with the same `AGENT_SEED` and it reconnects to the
same Agentverse entry and address. Do not delete and recreate inactive agents.

While registering later roles, keep the earlier roles active in one terminal:

```powershell
.\.venv\Scripts\python.exe run_agents.py --only ehr analytics triage documents workspace compliance
```

Each role uses its own local port. Connect the Inspector URLs for any roles not
yet registered. Once all roles are registered, this is also the recommended
single-machine specialist command.

For seven separately managed cloud workers, use the same repository and command:

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

After the Supervisor is registered, put its six specialist addresses in the
shared environment and run the entire stack together:

```powershell
.\.venv\Scripts\python.exe run_agents.py
```

All seven Agentverse entries should become Active. `Ctrl+C` stops the stack and
they become inactive until the same command is restarted.

## 5. Keep the agents online continuously

Agentverse Mailbox provides identity, queued delivery, discovery, and ASI:One
connectivity. The Python runtime still runs on your infrastructure. Choose one:

1. **Hackathon/local demo:** leave `run_agents.py` running on the laptop.
2. **Simplest persistent deployment:** deploy this repository as one background
   worker using `python run_agents.py`.
3. **Maximum failure isolation:** deploy seven workers, each with a distinct
   `AGENT_ROLE`, using `python deploy_agent.py`.

The repository includes `Dockerfile`, `.dockerignore`, and `Procfile`. For a
container worker, configure the common environment from section 2 plus all six
specialist addresses, then use the image's default command. Do not expose a port;
Mailbox mode makes outbound HTTPS connections.

The 52 MB synthetic dataset is intentionally packaged with the worker. Hosted
Agentverse agents are lightweight and have a restricted dependency environment;
this application relies on pandas, PyArrow, PDF libraries, and a local dataset,
so a persistent Mailbox worker is the direct deployment path. A later hosted
refactor should make Agentverse-hosted agents thin clients of a separately hosted
data service rather than uploading the current application unchanged.

### Connectivity failures

`503`, `getaddrinfo failed`, or `Network location cannot be reached` messages for
`agentverse.ai` mean the worker cannot currently resolve or reach Agentverse.
The mailbox client retries automatically, but the agent remains unavailable until
connectivity returns. Verify DNS/HTTPS access, VPN/firewall policy, and try a
different network. A cloud worker also removes dependence on the laptop network.

## 6. ASI:One acceptance flow

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

## 7. Submission evidence

Capture and publish:

- Supervisor and specialist Agentverse profile URLs;
- all seven stable addresses in the public README (never the seed);
- an ASI:One shared-chat URL showing the full workflow;
- screenshots of the live plan and approval card;
- a 3–5 minute demo video;
- the exact Git commit used for the deployment.
