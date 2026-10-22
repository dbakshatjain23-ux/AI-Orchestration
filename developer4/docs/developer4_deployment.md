# Developer 4 deployment runbook

## Recommended: local agents registered with Agentverse mailboxes

Use persistent local/VM/container storage for the dataset and SQLite. This avoids assuming that Agentverse hosted editors provide arbitrary package upload or durable SQLite files.

1. Follow README setup; run tests and the offline demo first.
2. Generate two distinct private seeds using `python -c "import secrets; print(secrets.token_hex(32))"`; put each only in your local `.env` or deployment secret manager. Stable seeds retain addresses. Never publish seeds, tokens, credential JSON, or `.env`.
3. Configure `ALLOWED_CALLERS` with the real supervisor agent address (comma separated, no spaces). Empty means deny all.
4. Start separate processes: `python agent_5_workspace_sync.py` and `python agent_6_compliance_audit.py`. Record their actual startup addresses; do not invent `agent1...` addresses.
5. Register each local agent through the Agentverse dashboard's current local-agent/mailbox onboarding flow. Set `AGENT_MAILBOX=true` when using mailbox transport and follow the dashboard connection instructions. Keep both processes running; mailbox registration is not cloud compute hosting.
6. The code includes each typed protocol with `publish_manifest=True`. Give Developer 1 the two addresses and `dev4/schemas.py`. Send signed typed requests from the allowlisted supervisor and verify replies and audit records. An unsigned/public REST request is not an authorized caller.
7. Verify a policy denial and a mock success, restart and replay the same request ID, then verify no second effect. Exercise independent ComplianceRequest checks. Keep real actions disabled for the demo.
8. If ASI:One discovery is needed, Developer 1's Chat Protocol supervisor must expose capabilities and route to these specialists. Custom typed protocol manifests alone do not make these agents chat-compatible.

## Hosted/cloud deployment

For a durable VM/container, deploy this entire repository plus its runtime dependencies. Run one supervised process per entry point, mount persistent state storage, and manage seeds/credentials through secrets. Both processes may share a SQLite file on the same host. Do not put SQLite on a network filesystem or create separate writable copies across replicas. Multi-host operation needs a transactional shared database and an authoritative consent source.

For Agentverse managed hosting, first verify the account's current package support, secret injection, dataset upload, and storage persistence. Copying an entry point alone will not work: it imports the `dev4` package and needs the real CSV. If durable SQLite and project files are unavailable, retain the local mailbox architecture or replace storage with a durable service before deployment. Do not claim successful deployment until the actual environment passes restart/replay tests. Other developers own the remaining agents; this implementation deploys only Agents 5 and 6.

## Acceptance and recovery

- Check distinct agent addresses, authenticated sender allowlist, typed replies, durable audit rows, and replay behavior after process restart.
- On uncertain or in_progress operations, inspect remote resources before administrator reconciliation. Never auto-expire a claim and repeat Gmail creation.
- Back up the database and secure its permissions. A remote success followed by local write failure can leave an in_progress claim; this is intentionally conservative.
- Real Google tests require explicit reviewed authorization, credentials, dedicated test destinations and opt-in flags. No live deployment or external action is performed by this runbook.

Official references checked during implementation:
- [uAgents communication](https://uagents.fetch.ai/docs/guides/communication)
- [Agentverse mailboxes](https://uagents.fetch.ai/docs/agentverse/mailbox)
- [ASI:One Chat Protocol](https://uagents.fetch.ai/docs/examples/asi-1)
- [Gmail drafts](https://developers.google.com/workspace/gmail/api/guides/drafts)
- [Calendar event creation](https://developers.google.com/workspace/calendar/api/guides/create-events)
