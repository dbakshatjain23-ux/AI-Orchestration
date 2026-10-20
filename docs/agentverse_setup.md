# Final Setup & Deployment on Agentverse Platform

## 1. Agentverse Platform Overview
Fetch.ai's **Agentverse (`agentverse.ai`)** is the cloud platform for registering, hosting, discovering, and executing autonomous `uAgents`. Hosting your agents on Agentverse ensures 24/7 uptime, survives local network drops during hackathon demos, and publishes Chat Protocol manifests directly into **ASI:One Chat (`asi1.ai/chat`)**.

---

## 2. Step-by-Step Deployment Instructions

### Step 1: Account Registration & Cloud Workspace
1. Sign in at `agentverse.ai` using GitHub, Google, or Fetch Wallet.
2. Navigate to **Profile Settings > API Keys** and generate an Agentverse API Key.

### Step 2: Creating Cloud Hosted Agents
For each of your 7 agents (1 Supervisor + 6 Specialists):
1. In Agentverse Dashboard, go to **My Agents** > **+ New Agent**.
2. Select **Hosted Agent**.
3. Name the agent (e.g., `Healthcare-Supervisor`, `Specialist-EHR-Search`).

### Step 3: Code Deployment & Secrets Storage
1. Paste the Python script for the agent into the Agentverse web editor.
2. In the **Secrets** tab of the Agentverse editor, add configuration keys securely:
   * `ASI_ONE_API_KEY`
   * `GOOGLE_SERVICE_ACCOUNT_JSON`
3. Ensure the sample dataset (`Sample_Dataset.csv`) is uploaded or available in the working directory.

### Step 4: Protocol Manifest Publishing
In each agent's code, include the Chat Protocol with `publish_manifest=True` to enable registration:

```python
agent.include(chat_proto, publish_manifest=True)
```

Click **Start** or **Deploy**. Upon starting, Agentverse registers the agent on the Fetch.ai directory and generates an immutable cryptographic address (e.g., `agent1q...`).

---

## 3. Specialist Capability Manifest Descriptions

To ensure ASI:One's planner accurately routes tasks, write narrow, precise capability descriptions in each published manifest:

| Agent Name | Crypto Address Format | Published Manifest Capability Description |
| :--- | :--- | :--- |
| **Supervisor Agent** | `agent1q_sup...` | Central Supervisor interface for healthcare workflows and clinical query planning. |
| **1. EHR Search Agent** | `agent1q_ehr...` | Queries patient demographics, medical history, admission dates, and single/multi-filter EHR records. |
| **2. Math & Analytics Agent** | `agent1q_math...` | Executes exact statistical math, average length of stay, percentage abnormal calculations, and hospital comparisons. |
| **3. Clinical Triage Agent** | `agent1q_triage...` | Evaluates patient acuity scores, clinical priority, human review requirements, and Level 2 emergency escalations. |
| **4. Document Generator** | `agent1q_doc...` | Compiles print-ready PDF discharge summaries, itemized accounting invoices, and administrative review reports. |
| **5. Workspace Sync Agent** | `agent1q_work...` | Integrates with Gmail for outreach, Google Calendar for review appointments, and Google Sheets for roster sync. |
| **6. Compliance & Audit Agent** | `agent1q_audit...` | Verifies patient consent (email/sms), checks contact allowances, and logs HIPAA audit event records. |

---

## 4. Testing & Verification in ASI:One Chat Interface

Once deployed and published on Agentverse:
1. Open the ASI:One chat interface (`asi1.ai/chat`).
2. Mention the Supervisor Agent in the chat input.
3. Submit a multi-agent prompt:
   > *"Identify all patients with abnormal test results and stays longer than 30 days, generate an administrative review PDF, sync the queue to Google Sheets, and prepare discharge follow-up emails."*
4. **Observe Execution**:
   * ASI:One's chat UI displays streamed task updates.
   * Verify sub-steps route to your specific specialist addresses.
   * Confirm the Human-in-the-Loop pause prompt appears before email dispatch.
