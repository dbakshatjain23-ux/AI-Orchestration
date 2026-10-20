# Complete Handoff File for LLM Coding Assistants

## 1. Codebase Blueprint & Directory Structure

To build the entire Healthcare Agent Orchestration System from scratch, structure your repository as follows:

```text
healthcare_agent_orchestration/
├── .env.example                  # Environment variables template
├── requirements.txt              # Python package dependencies
├── config.py                     # Central configuration & path bindings
├── Sample_Dataset.csv            # 76-column EHR sample dataset
├── agents/
│   ├── __init__.py
│   ├── supervisor_agent.py       # Central entry point & ASI:One Planner handler
│   ├── agent_1_ehr_search.py     # Multi-filter record lookup agent
│   ├── agent_2_math_analytics.py # Pandas-backed deterministic math agent
│   ├── agent_3_clinical_triage.py# Acuity, risk assessment & escalation agent
│   ├── agent_4_doc_generator.py # PDF report & invoice creation agent (fpdf2)
│   ├── agent_5_workspace_sync.py # Google Workspace agent (Gmail, Calendar, Sheets)
│   └── agent_6_compliance_audit.py# Consent verifier & HIPAA audit logging agent
├── utils/
│   ├── __init__.py
│   ├── dataset_loader.py         # CSV & SQLite database query wrapper
│   ├── pdf_builder.py            # fpdf2 PDF compilation helpers
│   └── google_client.py          # Google OAuth Service Account wrapper
└── main.py                       # Multi-agent process runner script
```

---

## 2. Dependencies (`requirements.txt`)
```text
uagents>=0.12.0
uagents-core>=0.2.0
requests>=2.31.0
pandas>=2.0.0
numpy>=1.24.0
fpdf2>=2.7.0
gspread>=5.10.0
google-api-python-client>=2.100.0
google-auth-httplib2>=0.1.1
google-auth-oauthlib>=1.1.0
python-dotenv>=1.0.0
```

---

## 3. Implementation Plan for Code Generation

### 3.1 Central Configuration (`config.py`)
- Load environment variables (`ASI_ONE_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_FILE`).
- Define dataset path bindings for `Sample_Dataset.csv`.
- Maintain list of 6 specialist agent addresses (`agent1q...`).

### 3.2 Supervisor Agent (`agents/supervisor_agent.py`)
- Initialize `uagents.Agent` with `uagents_core.contrib.protocols.chat`.
- Implement `ChatMessage` listener that sends HTTP POST requests to `/v1/chat/completions`.
- Include payload settings: `planner_mode: true`, `stream: true`, custom `x-session-id`, and specialist addresses.
- Detect `finish_reason == "tool_calls"` to pause for human approval before sending external communications.

### 3.3 Healthcare Math & Analytics Agent (`agents/agent_2_math_analytics.py`)
- Ingest `Sample_Dataset.csv` using Pandas.
- Compute exact average length of stay (LOS) per hospital or condition.
- Calculate exact percentage breakdowns of abnormal lab results.
- Perform group-by billing aggregations without LLM numerical hallucination.

### 3.4 Document Generator Agent (`agents/agent_4_doc_generator.py`)
- Use `fpdf2` library to compile formatted PDF documents.
- Support templates for Patient Discharge Summaries, Itemized Accounting Invoices, and 30+ Day Administrative Case Reviews.

### 3.5 Google Workspace Agent (`agents/agent_5_workspace_sync.py`)
- Authenticate via Google Cloud Service Account.
- Dispatch patient outreach emails via Gmail API.
- Create doctor review invites on Google Calendar.
- Sync real-time patient queues and billing records to Google Sheets via `gspread`.

### 3.6 Compliance & Audit Agent (`agents/agent_6_compliance_audit.py`)
- Check patient preferences (`email_consent`, `sms_consent`, `contact_allowed`).
- Block outreach when consent is missing or guardian verification is pending.
- Append HIPAA audit log events (`audit_event_type: "encounter_workflow_created"`).
