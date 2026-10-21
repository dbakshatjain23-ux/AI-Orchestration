# Agentverse Setup

The maintained deployment guide is [`agentverse_deployment.md`](agentverse_deployment.md).

CareFlow uses Agent Chat Protocol 0.3.0 and supports Agentverse mailbox deployment
through `deploy_agent.py`. Deploy and register the six specialists first, configure
their `agent1q...` addresses for the Supervisor, and deploy the Supervisor last.

Do not paste the local multi-file repository into seven blank Hosted Agent editors.
The dataset, shared modules, pandas/PyArrow processing, PDF dependencies, and cache
files belong in a normal Python runtime connected through Agentverse mailbox mode.
