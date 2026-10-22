import os
from pathlib import Path
from dotenv import load_dotenv
from .adapters import GoogleAdapter, MockAdapter
from .policy import Dataset, policy
from .schemas import ComplianceRequest, ComplianceResponse, WorkspaceRequest, WorkspaceResponse
from .service import WorkspaceService
from .store import Store

def build_agent(kind):
    from uagents import Agent, Context, Protocol
    load_dotenv()
    prefix = kind.upper()
    seed = os.environ[prefix + '_AGENT_SEED']
    port = int(os.getenv(prefix + '_PORT', '8005' if kind == 'workspace' else '8006'))
    mailbox = os.getenv('AGENT_MAILBOX', 'false') == 'true'
    agent = Agent(name='healthcare-' + kind, seed=seed, port=port, mailbox=mailbox,
                  endpoint=[] if mailbox else [f'http://127.0.0.1:{port}/submit'])
    dataset = Dataset(os.getenv('DATASET_PATH', 'data/healthcare_agent_testing_dataset_enhanced.csv'))
    path = Path(os.getenv('STATE_DB', 'runtime/dev4.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path)
    callers = set(filter(None, os.getenv('ALLOWED_CALLERS', '').split(',')))
    protocol = Protocol(name='healthcare-' + kind, version='1.0.0')
    if kind == 'workspace':
        mode = os.getenv('WORKSPACE_ADAPTER', 'mock')
        if mode not in ('mock', 'real'):
            raise ValueError('Unknown WORKSPACE_ADAPTER')
        service = WorkspaceService(dataset, store, GoogleAdapter() if mode == 'real' else MockAdapter(), callers)
        @protocol.on_message(model=WorkspaceRequest, replies={WorkspaceResponse})
        async def workspace(ctx: Context, sender: str, msg: WorkspaceRequest):
            # Blocking Google clients run outside the agent event loop.
            import asyncio
            response = await asyncio.to_thread(service.execute, msg, sender)
            await ctx.send(sender, WorkspaceResponse(**response))
    else:
        @protocol.on_message(model=ComplianceRequest, replies={ComplianceResponse})
        async def compliance(ctx: Context, sender: str, msg: ComplianceRequest):
            store.log(sender, msg, 'compliance_requested')
            reasons = ['unauthorized_caller']
            if sender in callers:
                try:
                    reasons = policy(dataset.get(msg.record_id), msg.action)
                except KeyError:
                    reasons = ['record_not_found']
            store.log(sender, msg, 'compliance_denied' if reasons else 'compliance_allowed', ','.join(reasons))
            await ctx.send(sender, ComplianceResponse(request_id=msg.request_id, allowed=not reasons, reasons=reasons))
    agent.include(protocol, publish_manifest=True)
    return agent
