"""Offline demo: uses dataset consent as-is; creates no approvals or external effects."""
from pathlib import Path
from dev4.policy import Dataset, policy
from dev4.store import Store
from dev4.adapters import MockAdapter
from dev4.schemas import WorkspaceRequest
from dev4.service import WorkspaceService

if __name__ == '__main__':
    ds = Dataset('data/healthcare_agent_testing_dataset_enhanced.csv')
    Path('runtime').mkdir(exist_ok=True)
    service = WorkspaceService(ds, Store('runtime/demo.sqlite3'), MockAdapter(), {'local-demo'})
    eligible = next(r for r in ds.rows.values() if not policy(r, 'gmail_draft'))
    for action in ('sheets_sync', 'gmail_draft', 'calendar_event'):
        request = WorkspaceRequest(request_id='demo-' + action, record_id=eligible['record_id'],
                                   action=action, start_at='2026-10-22T10:00:00+05:30',
                                   end_at='2026-10-22T11:00:00+05:30')
        print(service.execute(request, 'local-demo'))
    print(service.execute(WorkspaceRequest(request_id='blocked-demo', record_id='REC-000001',
                                          action='gmail_draft'), 'local-demo'))
