# CareFlow Documents

**Create readable administrative PDFs from source encounter data: discharge summaries, accounting reports and long-stay case reviews.**

## What it does

1. **Summarizes:** formats recorded patient and encounter information into a discharge-summary PDF.
2. **Documents billing:** creates an accounting/invoice PDF using supplied billing fields.
3. **Packages reviews:** generates bounded administrative case reviews for supplied cohorts or supported long-stay queries.

## Try it

- “Generate a discharge summary for PAT-000007.”
- “Generate an invoice for PAT-000007.”
- “Generate an administrative case review for stays over 30 days.”

For an exact encounter or cohort, use structured operations `discharge_summary`, `itemized_invoice` or `case_review` with source `record` or `records` data.

## Who it's for

Administrative staff, billing reviewers and supervisors assembling documented review outcomes.

## Details

- **Output:** a generated local PDF path; case-review output may also report the included case count.
- **Protocol:** Agent Chat Protocol; supported text requests and structured JSON operations.
- **Scope:** source-grounded formatting, not a signed clinical discharge decision, payment transaction or delivery service.
- **Limits:** a local path is not a public download link. The agent does not email documents. Direct specialist requests can generate files; the supervisor's reviewed package tool has a separate human-approval step.
- **Source:** [agent_4_doc_generator.py](https://github.com/dbakshatjain23-ux/AI-Orchestration/blob/codex/dev4-supervisor-integration/agents/agent_4_doc_generator.py).

Part of the seven-agent **CareFlow** system; demonstrations use synthetic healthcare data.
