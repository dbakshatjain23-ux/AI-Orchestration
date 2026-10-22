"""Safe integration of the supervisor with Developer 4's deterministic backend.

The in-process supervisor is the trusted caller here. Public specialist chat only
offers previews/checks, never execution or authorization grants. The standalone
typed agents remain available separately; do not start both sets on the same ports.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from config import settings
from developer4.dev4.adapters import MockAdapter
from developer4.dev4.policy import Dataset, policy
from developer4.dev4.schemas import WorkspaceRequest
from developer4.dev4.service import WorkspaceService
from developer4.dev4.store import Store, digest


class Developer4Bridge:
    actor = 'trusted-supervisor-process'

    def __init__(self, dataset=None, store=None, adapter=None):
        # This combined demo deliberately has no real Google execution route.
        if os.getenv('WORKSPACE_ADAPTER', 'mock') != 'mock':
            raise ValueError('Combined demo requires WORKSPACE_ADAPTER=mock')
        self.dataset = dataset if dataset is not None else Dataset(settings.dataset_path)
        path = Path(os.getenv('DEV4_STATE_DB', str(settings.output_dir / 'dev4.sqlite3')))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.store = store if store is not None else Store(path)
        self.adapter = adapter if adapter is not None else MockAdapter()
        if self.adapter.mode != 'mock':
            raise ValueError('Only mock adapters are supported by the combined demo')
        self.service = WorkspaceService(self.dataset, self.store, self.adapter, {self.actor})

    def request(self, arguments, request_id):
        return WorkspaceRequest(
            request_id=request_id, record_id=arguments['record_id'],
            action=arguments['action'], start_at=arguments.get('start_at', ''),
            end_at=arguments.get('end_at', ''),
        )

    def check(self, arguments, request_id='preview'):
        request = self.request(arguments, request_id)
        self.store.log(self.actor, request, 'integration_check_requested')
        try:
            reasons = policy(self.dataset.get(request.record_id), request.action)
        except KeyError:
            reasons = ['record_not_found']
        self.store.log(self.actor, request, 'integration_check_denied' if reasons else 'integration_check_allowed',
                       ','.join(reasons))
        return {'allowed': not reasons, 'reasons': reasons, 'record_id': request.record_id,
                'action': request.action, 'execution_performed': False}

    def execute(self, arguments, session_id, tool_call_id):
        if not session_id or not tool_call_id:
            raise ValueError('Stable session and tool call IDs are required')
        # Tool IDs are not assumed globally unique; include planner session identity.
        request_id = 'asi-' + digest({'session': session_id, 'tool': tool_call_id})[:48]
        result = self.service.execute(self.request(arguments, request_id), self.actor)
        return {**result, 'mode': 'mock', 'external_actions_executed': False,
                'action': arguments['action']}


@lru_cache(maxsize=1)
def get_dev4_bridge():
    return Developer4Bridge()


def specialist_preview(payload):
    if not isinstance(payload, dict) or not {'record_id', 'action'} <= payload.keys():
        return {'status': 'needs_input', 'message': 'Provide record_id and action. '
                'Actions: sheets_sync, gmail_draft, calendar_event. This endpoint checks '
                'policy only; the supervisor must request approval before mock execution.'}
    result = get_dev4_bridge().check(payload)
    return {'status': 'eligible_for_supervisor_review' if result['allowed'] else 'blocked', **result}
