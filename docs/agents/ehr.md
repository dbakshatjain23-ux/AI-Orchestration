# CareFlow EHR Search

**Find patient and encounter records using exact identifiers and supported healthcare operations filters.**

## What it does

1. **Retrieves:** looks up records by `patient_id` or `patient_full_name`.
2. **Filters:** selects cohorts by facility, condition, clinician, room, test result, age, stay length and billing.
3. **Returns evidence:** provides source fields, including `record_id` and `encounter_id`, for downstream agents.

## Try it

- “Show records for PAT-000007.”
- “Find patients with abnormal results and stays longer than 30 days.”

For an exact structured search, send this JSON as chat text:

```json
{"operation":"search","criteria":{"test_result":"Abnormal","length_of_stay_days__gt":30},"limit":10}
```

## Who it's for

Operations analysts and other CareFlow agents that need grounded records before calculating, reviewing or generating documents.

## Details

- **Data:** the supplied 55,500-row synthetic dataset; no live hospital EHR connection.
- **Output:** records and, depending on the operation, counts, criteria and truncation information. An empty result does not invent a replacement record.
- **Protocol:** Agent Chat Protocol; accepts supported plain-text patterns and structured JSON operations.
- **Identity:** `patient_id` may cover multiple encounters. Use the exact `record_id` for a workspace request.
- **Limits:** retrieval does not diagnose, approve outreach or grant consent.
- **Source:** [agent_1_ehr_search.py](https://github.com/dbakshatjain23-ux/AI-Orchestration/blob/codex/dev4-supervisor-integration/agents/agent_1_ehr_search.py).

Part of the seven-agent **CareFlow** system.
