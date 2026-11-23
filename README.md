# Agentic AI Job Tracker

An offline Python CLI that keeps job opportunities and applications in one local
SQLite database. **Milestone 1: a working tracking MVP.** This version provides
the data and tools for a future agent; it does not yet use an LLM or run an
autonomous agent. No API keys, network calls, or third-party Python packages are
required to run it or its tests.

## User problem

As a student or early-career job seeker, I collect opportunities across browser
tabs and job boards. I lose track of which roles I saved, which I applied to,
and when I applied. I need one quick, persistent record so I can review my
applications without searching through tabs and messages.

## MVP success criteria

| Criterion | How to verify |
| --- | --- |
| Record company, role, URL, status, and application date in one command | Run `add`; list the entry and check all fields |
| Keep entries after the CLI process exits | Add in one process, then list in a new process using the same database |
| Show a readable list, including a useful empty state | Run `list` on empty and populated databases |
| Reject blank fields, bad URLs, unsupported statuses, and invalid dates without saving them | Run the automated tests |
| Prevent duplicate entries for an identical URL without changing the original | Add the same URL twice; the second command fails clearly |
| Run locally without keys, services, or installed Python dependencies | Run the tests and demo using Python's standard library |
| Keep local job data, environments, and credentials out of commits | Review `.gitignore` and `git ls-files` |

## Quick start

Requires Python **3.10 or newer** with SQLite support (included in normal Python
installations). Run commands from the repository root. On Linux/macOS, use
`python3` if `python` is unavailable; on Windows, `py` also works.

```sh
python -m job_tracker add --company "Example AI" --role "Junior AI Engineer" --url "https://example.com/jobs/ai-engineer" --status applied --applied-date 2026-11-23
python -m job_tracker list
```

Example output on a fresh database:

```text
Added job #1: Example AI - Junior AI Engineer [applied]
ID  COMPANY     ROLE                STATUS   APPLIED DATE  URL
1   Example AI  Junior AI Engineer  applied  2026-11-23    https://example.com/jobs/ai-engineer
```

All example companies and URLs are fictional. The CLI records a job; it does
not submit an application or open its URL.

Save an opportunity before applying:

```sh
python -m job_tracker add --company "Example Labs" --role "Python Developer" --url "https://example.com/jobs/python"
```

Filter applications or get machine-readable output:

```sh
python -m job_tracker list --status applied
python -m job_tracker list --json
python -m job_tracker add --help
```

## Job entry model

| Field | Type | Rules |
| --- | --- | --- |
| `id` | Integer | Assigned by SQLite |
| `company` | String | Required, nonblank; outer whitespace is trimmed |
| `role` | String | Required, nonblank; outer whitespace is trimmed |
| `url` | String | Required absolute HTTP(S) URL, with a hostname and no credentials or whitespace; exact URL must be unique |
| `status` | String | `saved` (default), `applied`, `interview`, `offer`, `rejected`, or `withdrawn` |
| `applied_date` | ISO date string or null | Original application date in `YYYY-MM-DD` format; null for `saved` |

Use `--applied-date` for the application date. When adding with `--status applied`,
omitting the date uses today's date on your computer. All other nonsaved statuses
require an explicit original application date. A `saved` entry cannot have an
application date. Tabs, line breaks, and ASCII control characters are rejected
in company, role, and URL fields.

Listing returns newest entries first. Different URLs for the same job are not
automatically merged. Dates and URL syntax are checked locally; the CLI does
not check whether a job posting is still online.

## Local persistence

The default file is `~/.agentic-job-tracker/jobs.sqlite3` in your home directory,
so entries remain available when you run the CLI from another checkout.
For a custom file, put `--db` **before** `add` or `list`, and use the same path
for subsequent commands:

```sh
python -m job_tracker --db data/jobs.sqlite3 add --company "Example Labs" --role "Python Developer" --url "https://example.com/jobs/python"
python -m job_tracker --db data/jobs.sqlite3 list
```

Parent folders are created on the first add. Listing a missing database returns
an empty list without creating a file. SQL values use parameterized queries.
Duplicate URLs fail without overwriting data. Connections are closed after each
operation. Exit codes are `0` for success, `2` for invalid input or a duplicate,
and `1` for a database/filesystem error.

The database is a local, unencrypted file. `.gitignore` excludes SQLite files
and sidecars, `data/`, virtual environments, Python caches, `.env` files, and
common private-key extensions. The application has no API-key setting and never
reads credentials. Use an ignored path when exporting personal job data to JSON.

## Tests and end-to-end example

```sh
python -m unittest discover -s tests -v
python examples/demo.py
```

Tests cover validation, duplicate handling, SQL text treated as data, persistence
after reopening, ordering, filtering, date defaults, and CLI error messages.
The CLI tests start separate Python processes to exercise real disk persistence.

The demo creates a temporary database, lists it empty, adds one fictional job,
lists it in a fresh process, and checks every field through JSON output. It prints
`PASS` on success and removes its temporary data. Your normal database is not used.

## Project structure

| Path | Responsibility |
| --- | --- |
| `job_tracker/models.py` | JobEntry data model and validation |
| `job_tracker/storage.py` | SQLite persistence |
| `job_tracker/cli.py` | Argument parsing, add/list commands, and output |
| `job_tracker/__main__.py` | `python -m job_tracker` entry point |
| `tests/test_tracker.py` | Model, persistence, and CLI tests |
| `examples/demo.py` | Reproducible end-to-end example |

## Scope and next milestones

This MVP implements **add and list**. Editing statuses, deleting entries, job
scraping, CV matching, reminders, and automatic applications are not included.

1. Add status updates and application history without losing the original date.
2. Add an optional local-model adapter that can extract structured job details
   and explain a match against a user-provided CV, without requiring API keys.
3. Build an agent loop: read a user-selected posting, propose structured details,
   validate them, request the user's approval, and save the confirmed entry.
   Keep tool access restricted and evaluate extraction and matching quality.

The model and storage are separate from the CLI so future agent tools can reuse
the same validated records and persistence layer.
