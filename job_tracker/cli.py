"""Add and list job entries from the command line without network access."""

import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys

from .models import JobEntry, STATUSES
from .storage import JobStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track job applications locally with SQLite.")
    parser.add_argument(
        "--db", type=Path,
        default=Path.home() / ".agentic-job-tracker" / "jobs.sqlite3",
        help="SQLite file (default: ~/.agentic-job-tracker/jobs.sqlite3); use before the command",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="Save one job entry")
    add.add_argument("--company", required=True)
    add.add_argument("--role", required=True)
    add.add_argument("--url", required=True)
    add.add_argument("--status", choices=STATUSES, default="saved")
    add.add_argument(
        "--applied-date", metavar="YYYY-MM-DD",
        help="Original application date; defaults to today only for --status applied",
    )

    listing = commands.add_parser("list", help="List jobs, newest entry first")
    listing.add_argument("--status", choices=STATUSES, help="Filter by status")
    listing.add_argument("--json", action="store_true", help="Output a JSON array")
    return parser


def render_table(entries: list[JobEntry]) -> str:
    rows = [["ID", "COMPANY", "ROLE", "STATUS", "APPLIED DATE", "URL"]]
    rows.extend([
        str(entry.id), entry.company, entry.role, entry.status,
        entry.applied_date or "-", entry.url,
    ] for entry in entries)
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
        for row in rows
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = JobStore(args.db)
    try:
        if args.command == "add":
            applied_date = args.applied_date
            if args.status == "applied" and applied_date is None:
                applied_date = date.today().isoformat()
            entry = JobEntry(
                company=args.company, role=args.role, url=args.url,
                status=args.status, applied_date=applied_date,
            )
            saved = store.add(entry)
            print(f"Added job #{saved.id}: {saved.company} - {saved.role} [{saved.status}]")
        else:
            entries = store.list(args.status)
            if args.json:
                print(json.dumps([asdict(entry) for entry in entries], indent=2, ensure_ascii=False))
            elif entries:
                print(render_table(entries))
            else:
                print("No jobs found. Use 'python -m job_tracker add --help' to add one.")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error) as exc:
        print(f"Error: cannot access database at {store.db_path}: {exc}", file=sys.stderr)
        return 1
    return 0
