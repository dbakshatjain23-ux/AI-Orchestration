import base64
import os
import time
from email.message import EmailMessage

COLUMNS = ['record_id','patient_id','encounter_id','workflow_case_id','workflow_status']

class AdapterError(Exception):
    def __init__(self, code, uncertain=False):
        self.code, self.uncertain = code, uncertain
        super().__init__(code)

class MockAdapter:
    mode = 'mock'
    destination = {}
    def execute(self, req, row, fingerprint):
        return 'mock-' + fingerprint[:24]

class GoogleAdapter:
    mode = 'real'
    def __init__(self):
        if os.getenv('ENABLE_REAL_ACTIONS') != 'true':
            raise ValueError('Real actions disabled')
        self.destination = {k: os.getenv(k, '') for k in (
            'GOOGLE_SPREADSHEET_ID', 'GOOGLE_CALENDAR_ID', 'GOOGLE_DELEGATED_USER')} 
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        scopes = ['https://www.googleapis.com/auth/spreadsheets',
                  'https://www.googleapis.com/auth/gmail.compose',
                  'https://www.googleapis.com/auth/calendar.events']
        creds = service_account.Credentials.from_service_account_file(
            os.environ['GOOGLE_SERVICE_ACCOUNT_FILE'], scopes=scopes)
        if os.getenv('GOOGLE_DELEGATED_USER'):
            creds = creds.with_subject(os.environ['GOOGLE_DELEGATED_USER'])
        self.sheets = build('sheets', 'v4', credentials=creds, cache_discovery=False)
        self.gmail = build('gmail', 'v1', credentials=creds, cache_discovery=False)
        self.calendar = build('calendar', 'v3', credentials=creds, cache_discovery=False)

    def execute(self, req, row, fingerprint):
        from googleapiclient.errors import HttpError
        for attempt in range(3):
            try:
                if req.action == 'sheets_sync':
                    # Stable source row: update, never append. RAW prevents formula execution.
                    line = int(row['source_row_reference']) + 1
                    if line < 2:
                        raise ValueError('Invalid source row')
                    target = f"'Queue'!A{line}:E{line}"
                    self.sheets.spreadsheets().values().update(
                        spreadsheetId=os.environ['GOOGLE_SPREADSHEET_ID'], range=target,
                        valueInputOption='RAW', body={'values': [[row[k] for k in COLUMNS]]}
                    ).execute(num_retries=0)
                    return target
                if req.action == 'gmail_draft':
                    message = EmailMessage()
                    message['To'] = row['patient_email']
                    message['Subject'] = 'Care follow-up'
                    message.set_content('Please contact your care team through your secure patient portal.')
                    result = self.gmail.users().drafts().create(userId='me', body={
                        'message': {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}}
                    ).execute(num_retries=0)
                    return result['id']
                event_id = fingerprint[:40]
                result = self.calendar.events().insert(
                    calendarId=os.environ['GOOGLE_CALENDAR_ID'], sendUpdates='none',
                    body={'id': event_id, 'summary': 'Internal care review',
                          'start': {'dateTime': req.start_at}, 'end': {'dateTime': req.end_at}}
                ).execute(num_retries=0)
                return result['id']
            except HttpError as exc:
                status = int(exc.resp.status)
                if status == 409 and req.action == 'calendar_event':
                    # Verify that an existing event is the intended resource.
                    existing = self.calendar.events().get(calendarId=os.environ['GOOGLE_CALENDAR_ID'],
                                                          eventId=event_id).execute(num_retries=0)
                    if (existing.get('start', {}).get('dateTime') == req.start_at
                        and existing.get('end', {}).get('dateTime') == req.end_at):
                        return existing['id']
                    raise AdapterError('calendar_conflict') from None
                transient = status == 429 or status >= 500
                if transient and req.action != 'gmail_draft' and attempt < 2:
                    time.sleep(0.25 * 2 ** attempt)
                    continue
                raise AdapterError(f'google_http_{status}', uncertain=transient) from None
            except (TimeoutError, OSError):
                raise AdapterError('transport_error', uncertain=True) from None

