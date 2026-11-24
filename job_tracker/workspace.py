"""Account-scoped web storage. The original CLI database is deliberately separate."""

from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import secrets
import sqlite3
import time


class ConflictError(ValueError):
    pass


class MissingError(LookupError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL, preferences TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL, expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_attempts (
    id INTEGER PRIMARY KEY, ip TEXT NOT NULL, username TEXT NOT NULL, created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_time ON auth_attempts(created);
CREATE TABLE IF NOT EXISTS web_jobs (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company TEXT NOT NULL, role TEXT NOT NULL, url TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('saved','applied','interview','offer','rejected','withdrawn')),
    applied_date TEXT, location TEXT NOT NULL, work_mode TEXT NOT NULL,
    employment_type TEXT NOT NULL, language TEXT NOT NULL, german_level TEXT NOT NULL,
    office_days INTEGER, commute_minutes INTEGER,
    description TEXT NOT NULL, notes TEXT NOT NULL,
    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1, deleted_at INTEGER,
    CHECK ((status = 'saved' AND applied_date IS NULL) OR
           (status <> 'saved' AND applied_date IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS active_job_url ON web_jobs(user_id, url) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS owner_jobs ON web_jobs(user_id, deleted_at);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES web_jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL, created_at INTEGER NOT NULL
);
"""

FIELDS = (
    'company', 'role', 'url', 'status', 'applied_date', 'location', 'work_mode',
    'employment_type', 'language', 'german_level', 'office_days', 'commute_minutes',
    'description', 'notes',
)


class Workspace:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def session(self, token):
        if not token:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connection() as db:
            row = db.execute(
                'SELECT * FROM sessions WHERE token_hash=? AND expires>?',
                (digest, int(time.time())),
            ).fetchone()
            return dict(row) if row else None

    def new_session(self, user_id=None, old_token=None):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE expires <= ?', (now,))
            if old_token:
                db.execute('DELETE FROM sessions WHERE token_hash=?',
                           (hashlib.sha256(old_token.encode()).hexdigest(),))
            db.execute('INSERT INTO sessions VALUES (?, ?, ?, ?)',
                       (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, now + 604800))
        return token, csrf

    def allow_auth_attempt(self, ip, username, limit=10):
        now = int(time.time())
        with self.connection() as db:
            # Serialize count + insert so concurrent attempts cannot bypass the limit.
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM auth_attempts WHERE created < ?', (now - 900,))
            count = db.execute(
                'SELECT COUNT(*) FROM auth_attempts WHERE ip=? OR username=?', (ip, username),
            ).fetchone()[0]
            if count >= limit:
                return False
            db.execute('INSERT INTO auth_attempts(ip,username,created) VALUES (?,?,?)',
                       (ip, username, now))
        return True

    def register(self, username, password_hash):
        try:
            with self.connection() as db:
                return db.execute('INSERT INTO users(username,password_hash) VALUES (?,?)',
                                  (username, password_hash)).lastrowid
        except sqlite3.IntegrityError as exc:
            raise ConflictError('That username is already taken.') from exc

    def user_by_name(self, username):
        with self.connection() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            return dict(row) if row else None

    def user(self, user_id):
        with self.connection() as db:
            row = db.execute('SELECT id,username,preferences FROM users WHERE id=?', (user_id,)).fetchone()
            if not row:
                raise MissingError('Account not found.')
            return {'id': row['id'], 'username': row['username'], 'preferences': json.loads(row['preferences'])}

    def set_preferences(self, user_id, preferences):
        with self.connection() as db:
            db.execute('UPDATE users SET preferences=? WHERE id=?', (json.dumps(preferences), user_id))

    def list_jobs(self, user_id):
        with self.connection() as db:
            rows = db.execute(
                'SELECT * FROM web_jobs WHERE user_id=? AND deleted_at IS NULL ORDER BY updated_at DESC,id DESC',
                (user_id,),
            ).fetchall()
            return [self.public_job(row) for row in rows]

    @staticmethod
    def public_job(row):
        result = dict(row)
        result.pop('user_id', None)
        result.pop('deleted_at', None)
        return result

    def get_job(self, user_id, job_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM web_jobs WHERE id=? AND user_id=? AND deleted_at IS NULL',
                             (job_id, user_id)).fetchone()
            if not row:
                raise MissingError('Job not found.')
            history = [dict(event) for event in db.execute(
                'SELECT status,created_at FROM job_events WHERE job_id=? ORDER BY id', (job_id,))]
            return self.public_job(row), history

    def add_jobs(self, user_id, jobs):
        now = int(time.time())
        added = []
        try:
            with self.connection() as db:
                for job in jobs:
                    columns = ','.join(FIELDS)
                    marks = ','.join('?' for _ in FIELDS)
                    job_id = db.execute(
                        f'INSERT INTO web_jobs(user_id,{columns},created_at,updated_at) VALUES (?,{marks},?,?)',
                        (user_id, *(job[f] for f in FIELDS), now, now),
                    ).lastrowid
                    db.execute('INSERT INTO job_events(job_id,status,created_at) VALUES (?,?,?)',
                               (job_id, job['status'], now))
                    added.append(job_id)
        except sqlite3.IntegrityError as exc:
            raise ConflictError('A job with this URL is already saved. Nothing was imported.') from exc
        return added

    def update_job(self, user_id, job_id, job, version):
        now = int(time.time())
        try:
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM web_jobs WHERE id=? AND user_id=? AND deleted_at IS NULL',
                                 (job_id, user_id)).fetchone()
                if not old:
                    raise MissingError('Job not found.')
                if old['version'] != version:
                    raise ConflictError('This job changed in another tab. Close and reopen it before editing.')
                db.execute(
                    f'UPDATE web_jobs SET {",".join(f + "=?" for f in FIELDS)},updated_at=?,version=version+1 WHERE id=? AND user_id=?',
                    (*(job[f] for f in FIELDS), now, job_id, user_id),
                )
                if old['status'] != job['status']:
                    db.execute('INSERT INTO job_events(job_id,status,created_at) VALUES (?,?,?)',
                               (job_id, job['status'], now))
        except sqlite3.IntegrityError as exc:
            raise ConflictError('Another job already uses that URL.') from exc

    def delete_job(self, user_id, job_id, version):
        with self.connection() as db:
            cursor = db.execute(
                'UPDATE web_jobs SET deleted_at=?,version=version+1 WHERE id=? AND user_id=? AND version=? AND deleted_at IS NULL',
                (int(time.time()), job_id, user_id, version),
            )
            if cursor.rowcount == 0:
                row = db.execute('SELECT id FROM web_jobs WHERE id=? AND user_id=? AND deleted_at IS NULL',
                                 (job_id, user_id)).fetchone()
                if row:
                    raise ConflictError('This job changed. Refresh before deleting it.')
                raise MissingError('Job not found.')

    def restore_job(self, user_id, job_id):
        try:
            with self.connection() as db:
                cursor = db.execute(
                    'UPDATE web_jobs SET deleted_at=NULL,version=version+1 WHERE id=? AND user_id=? AND deleted_at IS NOT NULL',
                    (job_id, user_id),
                )
                if not cursor.rowcount:
                    raise MissingError('Deleted job not found.')
        except sqlite3.IntegrityError as exc:
            raise ConflictError('A saved job already has this URL. Edit it before restoring this one.') from exc
