"""SQLite persistence using parameterized queries and explicit connection cleanup."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3

from .models import JobEntry, STATUSES


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL CHECK (length(trim(company)) > 0),
    role TEXT NOT NULL CHECK (length(trim(role)) > 0),
    url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('saved', 'applied', 'interview', 'offer', 'rejected', 'withdrawn')
    ),
    applied_date TEXT,
    CHECK (
        (status = 'saved' AND applied_date IS NULL)
        OR (status <> 'saved' AND applied_date IS NOT NULL)
    )
)
"""


class DuplicateJobError(ValueError):
    """The exact job URL is already present."""


class JobStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def add(self, entry: JobEntry) -> JobEntry:
        with closing(self._connect()) as connection, connection:
            connection.execute(SCHEMA)
            cursor = connection.execute(
                """INSERT INTO jobs (company, role, url, status, applied_date)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO NOTHING""",
                (entry.company, entry.role, entry.url, entry.status, entry.applied_date),
            )
            if cursor.rowcount == 0:
                raise DuplicateJobError("a job with this URL already exists")
            return replace(entry, id=cursor.lastrowid)

    def list(self, status: str | None = None) -> list[JobEntry]:
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(STATUSES)}")
        if not self.db_path.exists():
            return []
        with closing(self._connect()) as connection, connection:
            connection.execute(SCHEMA)
            query = "SELECT id, company, role, url, status, applied_date FROM jobs"
            parameters: tuple[str, ...] = ()
            if status is not None:
                query += " WHERE status = ?"
                parameters = (status,)
            query += " ORDER BY id DESC"
            return [JobEntry(**dict(row)) for row in connection.execute(query, parameters)]
