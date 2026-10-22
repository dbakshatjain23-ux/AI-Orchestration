import csv
from datetime import datetime

REQUIRED = {'record_id','patient_id','patient_email','age_at_admission','contact_allowed',
            'email_consent','sms_consent','consent_status','consent_verified_at',
            'data_sharing_consent','human_review_required','human_review_status',
            'approval_id','approval_status','workflow_case_id','encounter_id','workflow_status','source_row_reference'}

class Dataset:
    def __init__(self, path):
        self.rows = {}
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if not REQUIRED.issubset(reader.fieldnames or []):
                raise ValueError('Dataset missing required fields')
            for row in reader:
                if row['record_id'] in self.rows:
                    raise ValueError('Duplicate record_id')
                self.rows[row['record_id']] = row

    def get(self, record_id):
        return self.rows[record_id]

def policy(row, action):
    reasons = []
    if row['consent_status'] != 'verified':
        reasons.append('consent_not_verified')
    try:
        stamp = datetime.fromisoformat(row['consent_verified_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp > datetime.now(stamp.tzinfo):
            raise ValueError()
    except (ValueError, TypeError):
        reasons.append('invalid_consent_verified_at')
    try:
        if int(row['age_at_admission']) < 18:
            reasons.append('guardian_review_required')
    except ValueError:
        reasons.append('invalid_age_at_admission')
    if row['data_sharing_consent'] != 'TRUE':
        reasons.append('data_sharing_not_allowed')
    if row['human_review_required'] not in ('TRUE', 'FALSE'):
        reasons.append('invalid_review_flag')
    if row['human_review_required'] == 'TRUE' and not (
        row['human_review_status'] == 'approved' and row['approval_status'] == 'approved'
        and row['approval_id']):
        reasons.append('human_review_required')
    if row['approval_status'] not in ('approved', 'not_required'):
        reasons.append('approval_unresolved')
    if action == 'gmail_draft':
        if row['contact_allowed'] != 'TRUE' or row['email_consent'] != 'TRUE':
            reasons.append('blocked_by_consent')
        if '@' not in row['patient_email'] or any(c in row['patient_email'] for c in '\r\n'):
            reasons.append('invalid_patient_email')
    return reasons

