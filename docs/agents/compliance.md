# CareFlow Compliance

**Explain whether recorded consent and review restrictions permit a workspace action, while keeping decisions traceable.**

## What it does

1. **Verifies source policy:** checks `consent_status`, `consent_verified_at`, `data_sharing_consent` and recorded review/approval fields.
2. **Checks contact permission:** Gmail drafts additionally require `contact_allowed` and `email_consent`; minor/guardian cases remain blocked.
3. **Explains and records:** returns eligibility and reason codes. The shared backend persists policy checks, execution evidence and duplicate-request state.

## Try it

Send structured JSON as chat text in integrated demo mode:

```json
{"record_id":"REC-000001","action":"gmail_draft"}
```

```json
{"record_id":"REC-000007","action":"sheets_sync"}
```

Supported actions are `gmail_draft`, `sheets_sync` and `calendar_event`. Use the exact source `record_id`. Missing required input returns `needs_input`; unsupported action values are rejected.

## Who it's for

Administrative reviewers and the CareFlow supervisor checking workflow restrictions and decision evidence.

## Details

- **Mode:** `ENABLE_DEV4_INTEGRATION=true`.
- **Output:** `allowed`, `reasons`, `record_id`, `action` and `execution_performed: false`, alongside the preview status.
- **Audit:** the integrated service uses persistent SQLite; the supervisor also records decision events in JSONL.
- **Protocol:** Agent Chat Protocol. This endpoint checks policy, not execution or authorization grants.
- **Limits:** user approval cannot manufacture consent or resolve pending review. Records are startup snapshots. Append-only SQL controls are not tamper-proof against an administrator; this agent does not certify regulatory compliance or send SMS/email.
- **Source:** [agent_6_compliance_audit.py](https://github.com/dbakshatjain23-ux/AI-Orchestration/blob/codex/dev4-supervisor-integration/agents/agent_6_compliance_audit.py).

Part of the seven-agent **CareFlow** system, using synthetic healthcare data.
