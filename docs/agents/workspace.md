# CareFlow Workspace 

**Check eligibility for Sheets queues, Gmail drafts and internal Calendar reviews before the supervisor runs a reviewed mock operation.**

## What it does

1. **Checks a request:** uses an exact `record_id` and requested workspace action.
2. **Explains eligibility:** returns `eligible_for_supervisor_review` or `blocked`, with policy reasons.
3. **Keeps execution separate:** the supervisor's workspace demo tool waits for a human decision, rechecks policy and records the mock result with duplicate protection.

## Try it

In the integrated demo mode, send either JSON request as chat text:

```json
{"record_id":"REC-000007","action":"gmail_draft"}
```

```json
{"record_id":"REC-000007","action":"sheets_sync"}
```

`calendar_event` is also supported. Execution requires timezone-aware `start_at` and `end_at`. To execute a mock operation, ask the supervisor; this specialist endpoint previews policy only.

## Who it's for

Operations teams demonstrating how reviewed workspace steps fit into a consent-aware workflow.

## Details

- **Mode:** `ENABLE_DEV4_INTEGRATION=true` and `WORKSPACE_ADAPTER=mock`.
- **Protocol:** Agent Chat Protocol. Use structured `record_id`/`action` input; other input returns `needs_input`.
- **Limits:** no real spreadsheet row, Gmail draft or calendar event is created in the integrated demo. A `mock-` ID is a simulation. Gmail sending is outside this draft-only interface. Real adapters exist separately but are not connected to this execution path.
- **Source:** [agent_5_workspace_sync.py](https://github.com/dbakshatjain23-ux/AI-Orchestration/blob/codex/dev4-supervisor-integration/agents/agent_5_workspace_sync.py).

Part of the seven-agent **CareFlow** system; uses recorded synthetic data and never grants consent.
