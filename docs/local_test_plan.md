# Local-First Verification Plan

Run these checks before adding ASI:One or Google credentials.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --build-index
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m benchmarks.benchmark_local --runs 3 --assert-budget
.\.venv\Scripts\python.exe smoke_local.py
```

Then verify deterministic workflows without external dispatch:

```powershell
.\.venv\Scripts\python.exe main.py "What proportion of all test results were abnormal?"
.\.venv\Scripts\python.exe workflow.py discharge PAT-000001
.\.venv\Scripts\python.exe workflow.py advanced-review --minimum-days 30 --no-outreach --max-pdf-cases 10
```

Expected safety properties:

- Tests and benchmarks pass.
- Seven Agent Chat Protocol services listen on ports 8000 through 8006.
- The smoke test reports `external_actions_executed: false`.
- PDFs are written under `output/`.
- Workspace actions remain prepared or mocked; nothing is sent to Gmail, Calendar, or Sheets.
- Approval denial and missing consent both resume the simulated planner session safely.

Only after this sequence passes should `.env` receive live ASI:One addresses and Google credentials.
