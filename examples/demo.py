"""Run an isolated end-to-end demo with temporary data and separate processes."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="job-tracker-demo-") as directory:
        command = [sys.executable, "-m", "job_tracker", "--db", str(Path(directory) / "jobs.sqlite3")]

        def run(*args: str) -> str:
            result = subprocess.run(
                [*command, *args], cwd=ROOT, check=True, capture_output=True,
                text=True, encoding="utf-8", timeout=10,
            )
            print(result.stdout, end="")
            return result.stdout

        print("1. Start with an empty database")
        run("list")
        print("\n2. Add a fictional application")
        run(
            "add", "--company", "Example AI", "--role", "Junior AI Engineer",
            "--url", "https://example.com/jobs/ai-engineer",
            "--status", "applied", "--applied-date", "2026-11-23",
        )
        print("\n3. Read persisted data in a new process")
        run("list")
        print("\n4. Check all fields through JSON output")
        entries = json.loads(run("list", "--json"))
        expected = [{
            "id": 1, "company": "Example AI", "role": "Junior AI Engineer",
            "url": "https://example.com/jobs/ai-engineer",
            "status": "applied", "applied_date": "2026-11-23",
        }]
        if entries != expected:
            raise RuntimeError(f"Demo persistence check failed: {entries!r}")
        print("\nPASS: add -> SQLite -> new process -> list preserves every field.")
    print("Temporary demo data removed; your own database was not used.")


if __name__ == "__main__":
    main()
