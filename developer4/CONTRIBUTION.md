# Developer 4 contribution

This folder contains the standalone Developer 4 implementation imported from
`sirishabh11/healthcare-agent-integrations`, commit `8f71cf2`.

The existing application at the repository root is preserved. These are separate
implementations. The root application's optional `ENABLE_DEV4_INTEGRATION=true`
mode now connects this backend to the existing supervisor and chat specialist
wrappers; see `../docs/combined_dev4_setup.md`. Do not launch both sets of agents
on the same ports.

Run this contribution from its own directory and use an isolated virtual environment:

```powershell
cd developer4
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python demo.py
python -m pytest -q
```

See README.md for policy and architecture, and docs/developer4_deployment.md for
Agentverse instructions. The included synthetic CSV is the exact source dataset.
No patient consent or approval is changed. Google actions default to mock mode;
Gmail integration creates drafts only.

Before integrating the two implementations, reconcile SDK versions (this folder
pins uagents 0.23.7; the parent currently requires uagents >=0.25.5), request schemas,
caller addresses, approval evidence, storage, and deployment entry points. Keep
this folder's environment separate until those differences have been tested.
