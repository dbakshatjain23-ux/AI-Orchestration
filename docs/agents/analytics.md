# CareFlow Analytics

**Turn encounter records into repeatable hospital operations statistics, calculated with Pandas rather than estimated by an LLM.**

## What it does

1. **Measures:** calculates average `length_of_stay_days` and the percentage of abnormal `test_result` values.
2. **Compares:** groups admission counts and billing summaries by supported source fields; compares conditions.
3. **Ranks:** returns bounded lists sorted by fields such as `billing_amount_usd`.

## Try it

- “What proportion of all test results were abnormal?”
- “Show average length of stay by facility.”
- “Show the top 10 records with the highest billing amounts.”

For an exact grouped calculation, send this JSON as chat text:

```json
{"operation":"average_length_of_stay","by":"facility_name"}
```

## Who it's for

Hospital operations analysts, administrative reviewers and the CareFlow supervisor.

## Details

- **Output:** calculated values, group summaries or ranked records, depending on the requested operation.
- **Supported structured operations:** `average_length_of_stay`, `abnormal_percentage`, `billing_summary`, `admission_counts`, `compare_conditions`, `top_records`.
- **Protocol:** Agent Chat Protocol; supported plain-text patterns and structured JSON.
- **Limits:** results describe the supplied synthetic data. They do not establish causation, predict patient outcomes or provide clinical advice. Unsupported requests need clarification.
- **Source:** [agent_2_math_analytics.py](https://github.com/dbakshatjain23-ux/AI-Orchestration/blob/codex/dev4-supervisor-integration/agents/agent_2_math_analytics.py).

Part of the seven-agent **CareFlow** system.
