# Combined supervisor and Developer 4 demo

The supervisor now has an opt-in path into the contributed Developer 4 policy,
mock adapters, persistent SQLite audit, and idempotency store. Agents 5 and 6 retain
the existing Agent Chat Protocol wrappers for ASI:One; in combined mode they offer
Developer 4 policy previews. The supervisor executes the reviewed mock operation
through the shared backend in its own process. This is not a claim that the
standalone typed agents are now remotely invoked by the supervisor.

There are still seven running agents. Do not start the standalone `developer4/`
entry points alongside them; they use the same ports. Use the root environment
with the newer root SDK requirements. The original standalone environment remains
separate. No clinical data or consent is modified.

## Local verification, without ASI or Google credentials

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe combined_demo.py --record-id REC-000007 --action gmail_draft --decision approve
.\.venv\Scripts\python.exe combined_demo.py --record-id REC-000001 --action gmail_draft --decision approve
.\.venv\Scripts\python.exe combined_demo.py --record-id REC-000007 --action gmail_draft --decision deny
```

REC-000007 is an actually eligible record in the supplied dataset, not a fabricated
approved record. REC-000001 is blocked. These commands use a scripted planner
instead of the ASI API, but invoke the real supervisor approval state machine and
Developer 4 backend. `--decision` is the operator's decision for this mock run; it
does not create patient consent or authorize real external operations. Audit and
claims persist in `output/dev4.sqlite3`; supervisor decisions also use its existing
JSONL audit. The demo prints the structured tool result rather than claiming a
success from the planner's narrative.

For a Calendar demo provide `--start-at` and `--end-at` with explicit timezones.

## Enable the combined mode for all seven agents

Create your private root `.env` from `.env.example` if none exists. Edit an existing
file without overwriting its secrets. Set:

```dotenv
ENABLE_DEV4_INTEGRATION=true
WORKSPACE_ADAPTER=mock
ENABLE_GOOGLE_ACTIONS=false
ENABLE_REAL_ACTIONS=false
```

Then run `python smoke_local.py` using the root environment to check startup, or
`python run_agents.py` to leave the seven agents running. Startup alone does not
prove message routing. In this mode the planner exposes `run_dev4_workspace_demo`
instead of the legacy Gmail-send, Calendar, and Sheets tools. Even if an old tool
call is received, the supervisor blocks legacy Google execution in combined mode.
The new tool accepts the exact `record_id` returned by EHR plus an action; it never
guesses among patient encounters. Its Calendar is an internal slot without
attendees; Gmail is a draft; Sheets is a stable-row sync. All three are simulations.

## Connect ASI:One

1. Keep the above safety flags. Store `ASI_ONE_API_KEY` and a private stable
   `AGENT_SEED` only in the local `.env`/secret manager. Never commit them.
2. Set `AGENT_MAILBOX=true` and follow `docs/agentverse_deployment.md` to register
   the six specialists, then the supervisor. Use `deploy_agent.py --agent <role>`
   or keep `run_agents.py` running with mailbox configuration. Mailboxes do not
   replace the running Python processes.
3. Put the actual six specialist addresses into `AGENT1_ADDRESS` through
   `AGENT6_ADDRESS`, then restart the supervisor. Never use example addresses.
4. Run `python check_asi_setup.py`. It prints only pass/fail configuration checks,
   not secrets. A passing check is not proof of live connectivity.
5. Run `python asi_chat.py` for an interactive API test, or @mention the registered
   supervisor in ASI:One Chat. API calls use your account and may incur charges.
6. Ask: "Find record REC-000007. Check its consent using the compliance specialist,
   then use run_dev4_workspace_demo to simulate a Gmail draft. Do not send mail."
   Verify the approval pause; approve only the mock operation. Repeat for
   REC-000001 and verify that approval cannot override its restrictions.

The local integration tests use a scripted ASI planner: they do not verify live
LLM planning or cloud message routing. Complete step 6 before claiming a successful
ASI:One deployment. Independent typed-agent network integration remains an
alternative future deployment design; the combined mode uses shared local services.

Official references:
- [ASI:One planner tools and specialist addresses](https://docs.asi1.ai/documentation/build-with-asi-one/planner)
- [Chat Protocol and mailbox setup](https://uagents.fetch.ai/docs/examples/asi-1)
