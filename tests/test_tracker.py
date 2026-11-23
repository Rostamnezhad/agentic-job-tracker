from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from job_tracker.models import JobEntry
from job_tracker.storage import DuplicateJobError, JobStore


ROOT = Path(__file__).resolve().parents[1]


class ModelTests(unittest.TestCase):
    def test_invalid_entries_are_rejected(self):
        base = dict(company="Example AI", role="AI Engineer", url="https://example.com/job")
        invalid = (
            {"company": "  "}, {"role": "\tEngineer"},
            {"url": "file:///tmp/jobs"}, {"url": "https://"},
            {"url": "https://example.com:invalid/job"},
            {"url": "https://name:password@example.com/job"},
            {"url": "https://example.com/a b"},
            {"status": "unknown"}, {"status": "interview"},
            {"status": "applied", "applied_date": "2026-02-30"},
            {"status": "applied", "applied_date": "20261123"},
            {"applied_date": "2026-11-23"},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                JobEntry(**(base | values))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "nested" / "jobs.sqlite3"

    def test_round_trip_persists_every_field_after_reopening(self):
        job = JobEntry(
            company="Example AI", role="Junior AI Engineer",
            url="https://example.com/jobs/1", status="applied", applied_date="2026-11-23",
        )
        saved = JobStore(self.path).add(job)
        self.assertEqual(saved.id, 1)
        self.assertEqual(JobStore(self.path).list(), [saved])

    def test_duplicate_url_does_not_overwrite_original(self):
        store = JobStore(self.path)
        original = store.add(JobEntry("Original", "Developer", "https://example.com/1"))
        with self.assertRaises(DuplicateJobError):
            store.add(JobEntry("Changed", "Engineer", "https://example.com/1"))
        self.assertEqual(store.list(), [original])

    def test_quotes_and_sql_text_are_stored_as_data(self):
        store = JobStore(self.path)
        job = store.add(JobEntry("O'Reilly'); DROP TABLE jobs; --", "R&D", "https://example.com/1"))
        self.assertEqual(store.list(), [job])
        store.add(JobEntry("Second", "Engineer", "https://example.com/2"))
        self.assertEqual(len(store.list()), 2)

    def test_filter_and_newest_first_order(self):
        store = JobStore(self.path)
        first = store.add(JobEntry("First", "Engineer", "https://example.com/1"))
        second = store.add(JobEntry("Second", "Engineer", "https://example.com/2", "applied", "2026-11-23"))
        self.assertEqual(store.list(), [second, first])
        self.assertEqual(store.list("applied"), [second])

    def test_fresh_list_is_empty_without_creating_a_database(self):
        self.assertEqual(JobStore(self.path).list(), [])
        self.assertFalse(self.path.exists())


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "jobs.sqlite3"

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "job_tracker", "--db", str(self.db), *arguments],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=10,
        )

    def add_args(self, *extra):
        return (
            "add", "--company", "Example AI", "--role", "Junior AI Engineer",
            "--url", "https://example.com/jobs/ai-engineer", *extra,
        )

    def test_add_then_list_in_separate_processes(self):
        added = self.run_cli(*self.add_args("--status", "applied", "--applied-date", "2026-11-23"))
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertIn("Added job #1", added.stdout)
        listed = self.run_cli("list", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        expected = JobEntry("Example AI", "Junior AI Engineer", "https://example.com/jobs/ai-engineer", "applied", "2026-11-23", 1)
        self.assertEqual(json.loads(listed.stdout), [asdict(expected)])

    def test_saved_job_default_and_readable_table(self):
        added = self.run_cli(*self.add_args())
        self.assertEqual(added.returncode, 0, added.stderr)
        listed = self.run_cli("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        for value in ("COMPANY", "ROLE", "STATUS", "APPLIED DATE", "URL", "saved", "Example AI"):
            self.assertIn(value, listed.stdout)
        self.assertIsNone(json.loads(self.run_cli("list", "--json").stdout)[0]["applied_date"])

    def test_applied_defaults_to_today(self):
        before = date.today().isoformat()
        added = self.run_cli(*self.add_args("--status", "applied"))
        after = date.today().isoformat()
        self.assertEqual(added.returncode, 0, added.stderr)
        entries = json.loads(self.run_cli("list", "--json").stdout)
        self.assertIn(entries[0]["applied_date"], (before, after))

    def test_empty_list(self):
        readable = self.run_cli("list")
        machine = self.run_cli("list", "--json")
        self.assertEqual(readable.returncode, 0, readable.stderr)
        self.assertIn("No jobs found", readable.stdout)
        self.assertEqual(machine.returncode, 0, machine.stderr)
        self.assertEqual(json.loads(machine.stdout), [])

    def test_invalid_input_exits_cleanly_without_writing(self):
        for extra in (
            ("--status", "unknown"),
            ("--status", "applied", "--applied-date", "2026-02-30"),
            ("--url", "not-a-url"),
            ("--company", "   "),
            ("--status", "interview"),
        ):
            with self.subTest(extra=extra):
                result = self.run_cli(*self.add_args(*extra))
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(self.db.exists())

    def test_duplicate_is_a_friendly_error_and_keeps_one_entry(self):
        first = self.run_cli(*self.add_args())
        self.assertEqual(first.returncode, 0, first.stderr)
        duplicate = self.run_cli(*self.add_args())
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("already exists", duplicate.stderr)
        self.assertNotIn("Traceback", duplicate.stderr)
        self.assertEqual(len(json.loads(self.run_cli("list", "--json").stdout)), 1)

    def test_status_filter_in_cli(self):
        added = self.run_cli(*self.add_args())
        self.assertEqual(added.returncode, 0, added.stderr)
        result = self.run_cli("list", "--status", "applied", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_unusable_database_path_returns_error(self):
        self.db.mkdir()
        result = self.run_cli(*self.add_args())
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot access database", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
