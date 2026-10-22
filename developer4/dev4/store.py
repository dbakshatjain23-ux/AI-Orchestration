import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS audit (
              seq INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL,
              request_id TEXT NOT NULL, record_id TEXT NOT NULL, event TEXT NOT NULL,
              detail TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
              BEGIN SELECT RAISE(ABORT, 'append only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
              BEGIN SELECT RAISE(ABORT, 'append only'); END;
            CREATE TABLE IF NOT EXISTS operations (
              key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, result TEXT);
            CREATE TABLE IF NOT EXISTS authorizations (
              fingerprint TEXT PRIMARY KEY, actor TEXT NOT NULL, evidence TEXT NOT NULL,
              expires_at TEXT NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def log(self, actor, req, event, detail=''):
        with self.db() as db:
            db.execute('INSERT INTO audit(at,actor,request_id,record_id,event,detail) VALUES(?,?,?,?,?,?)',
                       (datetime.now(timezone.utc).isoformat(), actor, req.request_id,
                        req.record_id, event, detail))

    def authorized(self, fingerprint, actor):
        with self.db() as db:
            row = db.execute('SELECT evidence,expires_at FROM authorizations WHERE fingerprint=? AND actor=?',
                             (fingerprint, actor)).fetchone()
        if not row or not row[0].strip():
            return False
        try:
            return datetime.fromisoformat(row[1]) > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False

    def claim(self, key, fingerprint):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fingerprint,state,result FROM operations WHERE key=?', (key,)).fetchone()
            if row:
                if row[0] != fingerprint:
                    return 'conflict', None
                return row[1], json.loads(row[2]) if row[2] else None
            db.execute('INSERT INTO operations VALUES(?,?,?,NULL)', (key, fingerprint, 'in_progress'))
            return 'new', None

    def finish(self, key, state, result):
        with self.db() as db:
            db.execute('UPDATE operations SET state=?,result=? WHERE key=?',
                       (state, json.dumps(result), key))

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
