"""Real supervisor state machine + real Developer 4 logic; no LLM/Google calls."""
from __future__ import annotations

import asyncio
import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agents.agent_1_ehr_search import EHRSearchAgent
from agents.supervisor_agent import PendingToolCall, SupervisorService, planner_tools
from config import ROOT_DIR, settings
from developer4.dev4.adapters import AdapterError, MockAdapter
from developer4.dev4.policy import Dataset, policy
from developer4.dev4.store import Store
from services.dev4_bridge import Developer4Bridge, specialist_preview
from tests.test_core import FakeCompliance, FakePlanner
from utils.dataset_loader import DatasetLoader


class CountingAdapter(MockAdapter):
    def __init__(self):
        self.calls = 0

    def execute(self, *args):
        self.calls += 1
        return super().execute(*args)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use unmodified rows from the actual synthetic data, never approved fixtures.
        cls.dataset = Dataset(ROOT_DIR / 'docs' / 'sample_dataset.csv')
        cls.eligible = next(dict(row) for row in cls.dataset.rows.values() if not policy(row, 'gmail_draft'))
        cls.blocked = dict(cls.dataset.get('REC-000001'))

    def setUp(self):
        base = ROOT_DIR / '.tmp' / 'integration-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.path = Path(self.tmp.name)
        csv_path = self.path / 'records.csv'
        with csv_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(self.eligible))
            writer.writeheader()
            writer.writerows([self.eligible, self.blocked])
        self.loader = DatasetLoader(csv_path)
        self.adapter = CountingAdapter()
        self.bridge = Developer4Bridge(Dataset(csv_path), Store(self.path / 'audit.sqlite3'), self.adapter)

    def tearDown(self):
        self.tmp.cleanup()

    def arguments(self, action='gmail_draft', record_id=None):
        return {'record_id': record_id or self.eligible['record_id'], 'action': action,
                'start_at': '2026-10-24T10:00:00+05:30' if action == 'calendar_event' else '',
                'end_at': '2026-10-24T10:30:00+05:30' if action == 'calendar_event' else ''}

    def supervisor(self, arguments):
        raw = {'id': 'call-dev4-1', 'type': 'function', 'function': {
            'name': 'run_dev4_workspace_demo', 'arguments': json.dumps(arguments)}}
        planner = FakePlanner([
            [{'choices': [{'delta': {'tool_calls': [raw]}}]}],
            [{'choices': [{'delta': {'content': 'Demo workflow finished.'}}]}],
        ])
        with patch('agents.supervisor_agent.settings', replace(settings, enable_dev4_integration=True)), \
             patch('services.dev4_bridge.get_dev4_bridge', return_value=self.bridge):
            service = SupervisorService(ehr=EHRSearchAgent(self.loader), planner=planner)
        service.compliance = FakeCompliance(allowed=True)
        return service, planner

    def run_flow(self, arguments, decision='approve'):
        service, planner = self.supervisor(arguments)
        before = self.adapter.calls
        first = asyncio.run(service.receive('test-human-session', 'Prepare a mock workspace operation'))
        self.assertIn('Approval required', first.content)
        self.assertEqual(self.adapter.calls, before)
        asyncio.run(service.receive('test-human-session', decision))
        results = [json.loads(m['content']) for m in planner.messages_seen[-1] if m['role'] == 'tool']
        self.assertEqual(planner.session_ids[0], planner.session_ids[1])
        return service, results[0]

    def test_approved_mock_flow_for_all_three_actions(self):
        for action in ('sheets_sync', 'gmail_draft', 'calendar_event'):
            with self.subTest(action=action):
                _, result = self.run_flow(self.arguments(action))
                self.assertEqual(result['status'], 'succeeded')
                self.assertTrue(result['resource_id'].startswith('mock-'))
                self.assertFalse(result['external_actions_executed'])

    def test_deny_never_executes(self):
        _, result = self.run_flow(self.arguments(), 'deny')
        self.assertEqual(result['status'], 'denied_by_user')
        self.assertEqual(self.adapter.calls, 0)

    def test_human_approval_cannot_override_record_restrictions(self):
        _, result = self.run_flow(self.arguments(record_id=self.blocked['record_id']))
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('blocked_by_consent', result['reasons'])
        self.assertEqual(self.adapter.calls, 0)

    def test_missing_record_is_not_invented(self):
        _, result = self.run_flow(self.arguments(record_id='REC-MISSING'))
        self.assertEqual(result['reasons'], ['record_not_found'])
        self.assertEqual(self.adapter.calls, 0)

    def test_restart_and_replay_preserve_result_and_audit(self):
        args = self.arguments()
        first = self.bridge.execute(args, 'session', 'tool')
        restarted = Developer4Bridge(self.bridge.dataset, Store(self.path / 'audit.sqlite3'), self.adapter)
        self.assertEqual(first, restarted.execute(args, 'session', 'tool'))
        self.assertEqual(self.adapter.calls, 1)
        with restarted.store.db() as db:
            events = [row[0] for row in db.execute('SELECT event FROM audit')]
        self.assertIn('execution_succeeded', events)
        self.assertIn('idempotent_replay', events)

    def test_changed_payload_conflicts(self):
        self.bridge.execute(self.arguments(), 'session', 'tool')
        result = self.bridge.execute(self.arguments('sheets_sync'), 'session', 'tool')
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(self.adapter.calls, 1)

    def test_specialists_preview_cannot_execute(self):
        with patch('services.dev4_bridge.get_dev4_bridge', return_value=self.bridge):
            result = specialist_preview({**self.arguments(), 'approved': True})
        self.assertEqual(result['status'], 'eligible_for_supervisor_review')
        self.assertFalse(result['execution_performed'])
        self.assertEqual(self.adapter.calls, 0)

    def test_legacy_google_send_blocked_even_if_enabled(self):
        service, _ = self.supervisor(self.arguments())
        service.allow_google_actions = True
        call = PendingToolCall('legacy', 'send_gmail_outreach', {}, {})
        result = service._execute_external_tool(call, 'session')
        self.assertEqual(result['reason'], 'legacy_google_actions_disabled_in_dev4_mode')

    def test_planner_only_exposes_mock_workspace_tool(self):
        with patch('agents.supervisor_agent.settings', replace(settings, enable_dev4_integration=True,
                                                               enable_google_actions=True)):
            names = [tool['function']['name'] for tool in planner_tools()]
        self.assertIn('run_dev4_workspace_demo', names)
        self.assertNotIn('send_gmail_outreach', names)

    def test_adapter_failure_returns_sanitized_uncertain_result(self):
        class Broken(CountingAdapter):
            def execute(self, *args):
                self.calls += 1
                raise AdapterError('transport_error', uncertain=True)
        broken = Broken()
        self.bridge.service.adapter = broken
        self.bridge.execute(self.arguments(), 'session', 'tool')
        result = self.bridge.execute(self.arguments(), 'session', 'tool')
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(broken.calls, 1)

    def test_real_mode_rejected(self):
        with patch.dict('os.environ', {'WORKSPACE_ADAPTER': 'real'}):
            with self.assertRaisesRegex(ValueError, 'requires WORKSPACE_ADAPTER=mock'):
                Developer4Bridge(self.bridge.dataset, self.bridge.store)


if __name__ == '__main__':
    unittest.main()
