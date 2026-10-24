# CareFlow Triage

**Make recorded priority, human-review and escalation flags visible so administrative cases can be reviewed with their source context.**

## What it does

1. **Reads priority:** reports `acuity_score` and `clinical_priority` from encounter records.
2. **Surfaces review needs:** returns `human_review_required` and `human_review_reason`.
3. **Reports escalation:** returns `escalation_required`, `escalation_level` and `escalation_owner_role`.

## Try it

- “Show the recorded triage flags for PAT-000001.”
- “Show human-review and escalation information for PAT-000007.”

For structured input, send the actual encounter JSON under a `record` key. It must contain `acuity_score`, `human_review_required` and `escalation_required`; use the values returned by EHR Search.

## Who it's for

Administrative reviewers and the CareFlow supervisor preparing source-grounded case reviews.

## Details

- **Output:** recorded priority, review and escalation fields; patient-ID lookup can return assessments for multiple encounters.
- **Protocol:** Agent Chat Protocol; patient-ID text or a structured record.
- **Limits:** this agent reports existing flags. It does not diagnose, invent thresholds, resolve reviews or dispatch emergency alerts. Reporting an L2 flag does not mean a clinician was notified.
- **Source:** [agent_3_clinical_triage.py](https://github.com/dbakshatjain23-ux/AI-Orchestration/blob/codex/dev4-supervisor-integration/agents/agent_3_clinical_triage.py).

Part of the seven-agent **CareFlow** system.
