# Complete Tech Stack & System Architecture Document

## 1. Stack Layer Breakdown

The **Healthcare Agent Orchestration System** combines a decentralized agent runtime, LLM-based multi-agent planning, deterministic data handling, programmatic document compilation, and Google Workspace integrations.

### Components:
1. **User Interface**: ASI:One Native Chat Interface (`asi1.ai/chat`).
2. **Orchestration Layer**: Supervisor uAgent communicating with the ASI:One Chat Completions API with `planner_mode: true`.
3. **Specialized Agent Layer**: 6 domain-specific uAgents built with Python `uagents` framework.
4. **Data & External Integrations Layer**: Pandas/SQLite over `Sample_Dataset.csv`, `fpdf2` for PDFs, and Google Workspace APIs (Gmail, Google Calendar, Google Sheets).

---

## 2. Technology Matrix

| Stack Component | Chosen Technology | Version / Requirement | Purpose |
| :--- | :--- | :--- | :--- |
| **Language** | Python | `3.10+` | Core agent logic, data manipulation, and API scripting. |
| **Agent Framework** | `uagents` | `>= 0.12.0` | Autonomous agent runtime, protocol binding, and address generation. |
| **Protocol** | `uagents-core` | `contrib.protocols.chat` | Agent Chat Protocol standard for ASI:One compatibility. |
| **LLM Orchestration** | ASI:One Planner | `/v1/chat/completions` | Multi-step task decomposition and specialist routing. |
| **Cloud Platform** | Fetch.ai Agentverse | `agentverse.ai` | Agent hosting, manifest publishing, and discovery. |
| **Data Engine** | Pandas & SQLite3 | `pandas >= 2.0.0` | Exact, deterministic healthcare calculations. |
| **PDF Generation** | `fpdf2` | `>= 2.7.0` | Programmatic PDF report and invoice compilation. |
| **Google Integration** | Google Cloud APIs | `gspread`, `google-api-python-client` | Gmail, Calendar, Sheets integration. |

---

## 3. Architectural System Diagram
```mermaid
graph TB
    subgraph FrontEnd [User Interface]
        UI[ASI:One Chat Interface]
    end

    subgraph CoreOrchestrator [Supervisor & Planning Layer]
        Sup[Supervisor uAgent]
        ASI1[ASI:One LLM Planner Engine]
    end

    subgraph SpecialistAgents [Specialized uAgents Layer]
        A1[1. EHR Search Agent]
        A2[2. Math & Analytics Agent]
        A3[3. Clinical Triage Agent]
        A4[4. Document Generator Agent]
        A5[5. Google Workspace Agent]
        A6[6. Compliance & Audit Agent]
    end

    subgraph DataServices [External APIs & Data Storage]
        DB[(Sample_Dataset.csv / SQLite)]
        PDF[PDF Storage Engine - fpdf2]
        GSuite[Google Workspace APIs]
    end

    UI <-->|Agent Chat Protocol| Sup
    Sup <-->|ASI:One Planner API| ASI1
    ASI1 -->|Task Directives| A1
    ASI1 -->|Task Directives| A2
    ASI1 -->|Task Directives| A3
    ASI1 -->|Task Directives| A4
    ASI1 -->|Task Directives| A5
    ASI1 -->|Task Directives| A6

    A1 <-->|SQL/Pandas Queries| DB
    A2 <-->|Deterministic Math| DB
    A3 <-->|Acuity/L2 Rules| DB
    A4 -->|Compile PDF| PDF
    A5 <-->|REST API| GSuite
    A6 <-->|Consent & Audit Check| DB
```
