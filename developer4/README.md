# Developer 4: Workspace Sync and Compliance

Python 3.12 implementation for two independent uAgents. All five original documents in `docs/` were reviewed. Their references to `Sample_Dataset.csv`, guardian flags, send-mail, and approved workflows are superseded here by the actual 76-column CSV and draft-only scope. No credentials or approvals are supplied.

## Quick start (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python demo.py
Copy-Item .env.example .env
```

The offline demo selects an actually eligible row without modifying its consent, exercises three mock actions, replays safely across restarts, and shows a denied record. `mock-` IDs are local simulations, not Google resources. The two pre-existing empty consent files are left untouched.

## Architecture and policy

`dev4/policy.py` indexes the authoritative CSV by `record_id`, avoiding ambiguity between patient and encounter. Required headers and duplicate record IDs fail startup. The shipped dataset has 55,500 records, 76 columns, and no approved reviews. Consent is never inferred from synthetic status, email availability, emergency status, or an LLM response.

Every action requires verified consent with a timezone-aware verification timestamp, adult age at admission, `data_sharing_consent == TRUE`, and resolved review/approval. Gmail additionally requires `contact_allowed`, `email_consent`, and a valid basic recipient. Unknown values fail closed. Guardian cases remain blocked because this dataset provides no sufficient guardian authorization evidence. Calendar is an internal review slot with no patient attendees; Sheets is an internal workflow queue. SMS is unsupported; `sms_consent` does not authorize email. Historical admission age is treated conservatively, not recomputed into current adulthood.

`dev4/agents.py` creates independent Workspace and Compliance processes, identities, typed request/reply protocols, and published manifests. Compliance is independently queryable. Workspace also enforces the same policy directly, avoiding a time-of-check/time-of-use gap or forged compliance response. The authenticated uAgent sender must appear in `ALLOWED_CALLERS`. Do not add an actor or approved boolean to request payloads. Request schemas are in `dev4/schemas.py`; send `WorkspaceRequest` to Agent 5 and `ComplianceRequest` to Agent 6 with the supervisor's signed `ctx.send`. Both replies echo `request_id`.

SQLite persists request receipts, denials, execution intent, results, and replay events. Logs contain identifiers and reason codes rather than clinical content, email bodies, or raw API exceptions. SQL triggers prohibit ordinary updates/deletes; this is **not** tamper-proof storage or a claim of HIPAA compliance. Restrict database/CSV access, encrypt disks, and define retention and external immutable backups before production.

An atomic SQLite claim prevents concurrent duplicate execution. Keys bind caller, request ID, and adapter mode; fingerprints also bind action, record, and interval. Reusing a key with different parameters conflicts. Policy is checked again before replay. Sheets uses stable `source_row_reference` rows and RAW values; Calendar uses a deterministic event ID. Gmail draft creation has no native idempotency key: ambiguous failures or process crashes remain blocked for operator reconciliation. Exactly-once remote delivery is not claimed. Do not delete claims and retry blindly. Audit or database failures stop execution. Each process loads a CSV snapshot: restart both after authoritative dataset updates; use a transactional shared source for production revocation.

## Real Google adapters (explicit opt-in)

Set `WORKSPACE_ADAPTER=real` AND `ENABLE_REAL_ACTIONS=true`. Supply credentials by file path through `GOOGLE_SERVICE_ACCOUNT_FILE`; never paste keys into code. Set spreadsheet/calendar IDs and, for Gmail, `GOOGLE_DELEGATED_USER`. Gmail requires Workspace domain-wide delegation authorized by a domain administrator; a plain service account cannot access a user's Gmail inbox. Consumer Gmail requires a separate user OAuth adapter, which is not implemented.

Enable Sheets, Gmail and Calendar APIs. Grant only the configured scopes: spreadsheets, gmail.compose, calendar.events. Gmail compose scope technically permits sending, but this code only calls drafts.create and exposes no send operation. Share only the target sheet/calendar with the service account; pre-create a dedicated `Queue` tab with header fields `record_id,patient_id,encounter_id,workflow_case_id,workflow_status`. Reserve rows for this source dataset; source-row positions must remain stable. No Drive scope is needed.

Real operations also require an administrator-provisioned `authorizations` database entry: fingerprint, authenticated actor, nonempty human approval evidence/reference, and a timezone-aware future `expires_at`. Compute the fingerprint with `digest({'actor': actor, 'request': request.model_dump(), 'mode': 'real', 'destination': adapter.destination})`. This deliberately has no remote grant endpoint. An administrator must review the exact action and destination configuration and insert evidence through a trusted local administrative process; the agents never fabricate it. Protect and freeze destination configuration during an authorization window. Dataset review approval and external action authorization are separate requirements. The repository contains no granted authorizations.

Google 429/5xx responses have bounded retries for stable Sheets/Calendar operations; Gmail is not blindly retried. Terminal permission/validation errors are returned as sanitized codes. All adapter failures retain a reconciliation claim conservatively. Inspect the Google resource and audit history before manual recovery. Calendar never sends attendee updates; Gmail never sends messages.

## Agentverse / supervisor integration

See [deployment instructions](docs/developer4_deployment.md). These agents implement typed specialist protocols; publishing them does not by itself implement ASI:One Chat. The Developer 1 supervisor must translate reviewed planner/tool requests into these schemas, retain request IDs on retries, and display structured denials. No public chat handler can bypass authorization.

## Validation

Tests cover actual schema, consent/review/guardian denials, caller authorization, missing records, mock operations, restart replay, key conflicts, concurrent claims, revocation before replay, ambiguous API failure suppression, real authorization gating, Calendar intervals, and independent agent construction. Real API and Agentverse network acceptance require separately configured credentials and are not part of offline tests.

