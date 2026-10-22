import csv
from concurrent.futures import ThreadPoolExecutor
import pytest
from dev4.policy import Dataset, policy
from dev4.store import Store
from dev4.adapters import MockAdapter, AdapterError
from dev4.schemas import WorkspaceRequest
from dev4.service import WorkspaceService

@pytest.fixture(scope='session')
def source_dataset():
    return Dataset('data/healthcare_agent_testing_dataset_enhanced.csv')

@pytest.fixture
def setup(tmp_path, source_dataset):
    from copy import copy
    ds = copy(source_dataset)
    ds.rows = dict(source_dataset.rows)
    row = next(r for r in ds.rows.values() if not policy(r, 'gmail_draft'))
    row = dict(row)
    ds.rows[row['record_id']] = row
    store = Store(tmp_path / 'state.sqlite3')
    service = WorkspaceService(ds, store, MockAdapter(), {'supervisor'})
    req = WorkspaceRequest(request_id='demo-1', record_id=row['record_id'], action='gmail_draft')
    return ds, row, store, service, req

def test_actual_schema(setup):
    ds, row, *_ = setup
    assert len(ds.rows) == 55500
    assert len(row) == 76
    assert {r['approval_status'] for r in ds.rows.values()} == {'pending','escalated','not_required'}

@pytest.mark.parametrize('field,value,reason', [
    ('email_consent','FALSE','blocked_by_consent'),
    ('contact_allowed','FALSE','blocked_by_consent'),
    ('consent_status','guardian_required','consent_not_verified'),
    ('age_at_admission','15','guardian_review_required'),
    ('consent_verified_at','','invalid_consent_verified_at'),
    ('data_sharing_consent','FALSE','data_sharing_not_allowed'),
    ('human_review_required','TRUE','human_review_required'),
    ('approval_status','pending','approval_unresolved')])
def test_policy_denials(setup, field, value, reason):
    row = dict(setup[1]); row[field] = value
    assert reason in policy(row, 'gmail_draft')

def test_authorization_and_unknown_record(setup):
    _, _, _, service, req = setup
    assert service.execute(req, 'stranger')['reasons'] == ['unauthorized_caller']
    req.record_id = 'missing'
    assert service.execute(req, 'supervisor')['reasons'] == ['record_not_found']

def test_replay_restart_and_conflict(setup):
    ds, row, store, service, req = setup
    first = service.execute(req, 'supervisor')
    assert first['status'] == 'succeeded'
    restarted = WorkspaceService(ds, Store(store.path), MockAdapter(), {'supervisor'})
    assert restarted.execute(req, 'supervisor') == first
    req.action = 'sheets_sync'
    assert restarted.execute(req, 'supervisor')['status'] == 'conflict'
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM audit').fetchone()[0] >= 6
        with pytest.raises(Exception):
            db.execute('DELETE FROM audit')

def test_revocation_precedes_replay(setup):
    ds, row, store, service, req = setup
    service.execute(req, 'supervisor')
    row['email_consent'] = 'FALSE'
    assert service.execute(req, 'supervisor')['status'] == 'blocked'

def test_concurrent_claim(setup):
    store = setup[2]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.claim('same', 'hash')[0], range(8)))
    assert results.count('new') == 1

def test_ambiguous_failure_never_retried(setup):
    class Broken(MockAdapter):
        calls = 0
        def execute(self, *args):
            self.calls += 1
            raise AdapterError('timeout', uncertain=True)
    service, req = setup[3:]
    service.adapter = Broken()
    assert service.execute(req, 'supervisor')['status'] == 'uncertain'
    assert service.execute(req, 'supervisor')['status'] == 'uncertain'
    assert service.adapter.calls == 1

def test_real_requires_provisioned_authorization(setup):
    class Real(MockAdapter):
        mode = 'real'
        def execute(self, *args):
            pytest.fail('Must not execute')
    service, req = setup[3:]
    service.adapter = Real()
    assert service.execute(req, 'supervisor')['reasons'] == ['external_authorization_required']

@pytest.mark.parametrize('start,end', [('', ''), ('2026-10-22T10:00:00','2026-10-22T11:00:00'),
    ('2026-10-22T11:00:00Z','2026-10-22T10:00:00Z')])
def test_bad_calendar(setup, start, end):
    service, req = setup[3:]
    req.action = 'calendar_event'; req.start_at = start; req.end_at = end
    assert service.execute(req, 'supervisor')['reasons'] == ['invalid_calendar_interval']

@pytest.mark.parametrize('action', ['sheets_sync','gmail_draft','calendar_event'])
def test_mock_actions(setup, action):
    service, req = setup[3:]
    req.action = action
    req.start_at = '2026-10-22T10:00:00+05:30'; req.end_at = '2026-10-22T11:00:00+05:30'
    assert service.execute(req, 'supervisor')['resource_id'].startswith('mock-')

def test_agent_construction(tmp_path, monkeypatch):
    from dev4.agents import build_agent
    # Isolate SDK chain discovery; no network calls belong in offline tests.
    monkeypatch.setattr('uagents.agent.get_almanac_contract', lambda network: None)
    monkeypatch.setenv('WORKSPACE_AGENT_SEED', 'test-only-workspace-seed')
    monkeypatch.setenv('COMPLIANCE_AGENT_SEED', 'test-only-compliance-seed')
    monkeypatch.setenv('STATE_DB', str(tmp_path / 'agents.sqlite3'))
    monkeypatch.setenv('WORKSPACE_ADAPTER', 'mock')
    a, b = build_agent('workspace'), build_agent('compliance')
    assert a.address != b.address
    import asyncio
    loop = asyncio.get_event_loop()
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(asyncio.sleep(0))

def test_google_adapter_request_contracts(setup, monkeypatch):
    from unittest.mock import MagicMock
    from dev4.adapters import GoogleAdapter
    adapter = GoogleAdapter.__new__(GoogleAdapter)
    adapter.sheets = MagicMock(); adapter.gmail = MagicMock(); adapter.calendar = MagicMock()
    monkeypatch.setenv('GOOGLE_SPREADSHEET_ID', 'test-sheet')
    monkeypatch.setenv('GOOGLE_CALENDAR_ID', 'test-calendar')
    _, row, _, _, req = setup
    req.action = 'sheets_sync'
    adapter.execute(req, row, 'a' * 64)
    kwargs = adapter.sheets.spreadsheets.return_value.values.return_value.update.call_args.kwargs
    assert kwargs['valueInputOption'] == 'RAW'
    assert kwargs['body']['values'][0][0] == row['record_id']
    req.action = 'gmail_draft'
    adapter.gmail.users.return_value.drafts.return_value.create.return_value.execute.return_value = {'id':'draft-1'}
    assert adapter.execute(req, row, 'a' * 64) == 'draft-1'
    adapter.gmail.users.return_value.messages.return_value.send.assert_not_called()
    req.action = 'calendar_event'
    adapter.calendar.events.return_value.insert.return_value.execute.return_value = {'id':'a' * 40}
    adapter.execute(req, row, 'a' * 64)
    kwargs = adapter.calendar.events.return_value.insert.call_args.kwargs
    assert kwargs['sendUpdates'] == 'none'
    assert 'attendees' not in kwargs['body']


def test_google_retries_only_stable_operations(setup, monkeypatch):
    from unittest.mock import MagicMock
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    from dev4.adapters import GoogleAdapter
    monkeypatch.setenv('GOOGLE_SPREADSHEET_ID', 'test-sheet')
    monkeypatch.setattr('dev4.adapters.time.sleep', lambda _: None)
    adapter = GoogleAdapter.__new__(GoogleAdapter)
    adapter.sheets = MagicMock(); adapter.gmail = MagicMock()
    error = HttpError(Response({'status':503}), b'{}')
    _, row, _, _, req = setup
    req.action = 'sheets_sync'
    call = adapter.sheets.spreadsheets.return_value.values.return_value.update.return_value.execute
    call.side_effect = [error, {}]
    adapter.execute(req, row, 'b' * 64)
    assert call.call_count == 2
    req.action = 'gmail_draft'
    call = adapter.gmail.users.return_value.drafts.return_value.create.return_value.execute
    call.side_effect = error
    with pytest.raises(AdapterError):
        adapter.execute(req, row, 'b' * 64)
    assert call.call_count == 1


