from datetime import datetime
from .policy import policy
from .store import digest
from .adapters import AdapterError

class WorkspaceService:
    def __init__(self, dataset, store, adapter, allowed_callers):
        self.dataset, self.store, self.adapter = dataset, store, adapter
        self.allowed_callers = set(allowed_callers)

    def execute(self, req, actor):
        result = {'request_id': req.request_id, 'status': 'blocked', 'reasons': [], 'resource_id': ''}
        self.store.log(actor, req, 'request_received')
        if actor not in self.allowed_callers:
            result['reasons'] = ['unauthorized_caller']
        else:
            try:
                row = self.dataset.get(req.record_id)
            except KeyError:
                result['reasons'] = ['record_not_found']
            else:
                result['reasons'] = policy(row, req.action)
        if result['reasons']:
            self.store.log(actor, req, 'request_denied', ','.join(result['reasons']))
            return result
        if req.action == 'calendar_event':
            try:
                start, end = [datetime.fromisoformat(v.replace('Z', '+00:00'))
                              for v in (req.start_at, req.end_at)]
                if start.tzinfo is None or end.tzinfo is None or end <= start:
                    raise ValueError()
            except ValueError:
                result['reasons'] = ['invalid_calendar_interval']
                self.store.log(actor, req, 'request_denied', 'invalid_calendar_interval')
                return result
        fingerprint = digest({'actor': actor, 'request': req.model_dump(), 'mode': self.adapter.mode, 'destination': self.adapter.destination})
        if self.adapter.mode == 'real' and not self.store.authorized(fingerprint, actor):
            result['reasons'] = ['external_authorization_required']
            self.store.log(actor, req, 'request_denied', 'external_authorization_required')
            return result
        key = digest({'actor': actor, 'request_id': req.request_id, 'mode': self.adapter.mode})
        state, previous = self.store.claim(key, fingerprint)
        if state == 'succeeded':
            self.store.log(actor, req, 'idempotent_replay')
            return previous
        if state != 'new':
            result.update(status=state, reasons=['reconciliation_required' if state != 'conflict' else 'idempotency_conflict'])
            self.store.log(actor, req, 'duplicate_blocked', state)
            return result
        # Persist intent before the remote effect. A crash leaves an in_progress claim.
        self.store.log(actor, req, 'execution_started')
        try:
            resource = self.adapter.execute(req, row, fingerprint)
        except Exception as exc:
            code = exc.code if isinstance(exc, AdapterError) else 'adapter_failure'
            result.update(status='uncertain', reasons=[code, 'reconciliation_required'])
            self.store.finish(key, 'uncertain', result)
            self.store.log(actor, req, 'execution_uncertain', code)
            return result
        result.update(status='succeeded', resource_id=resource)
        self.store.finish(key, 'succeeded', result)
        self.store.log(actor, req, 'execution_succeeded')
        return result


