# Agentic AI Job Tracker

A Python job-search workspace with private accounts, application tracking, and
**optional Tavily-powered discovery across ten selected sources**. Tracking works
offline without keys. Live discovery requires your own Tavily free-plan API key.

**Milestone 3: profile → bounded search → ranked leads → review → save.** The
workflow searches public indexed pages on demand, normalizes/deduplicates URLs,
and explains keyword relevance. It does not log into job sites, run an LLM,
verify every job requirement, or submit applications.

## User problem

Job seekers collect opportunities across tabs, job boards, and messages. They
lose track of application dates, next steps, and requirements such as language,
commuting distance, and office attendance. A browser interface makes tracking
accessible to people who do not use a terminal every day.

This project provides one personal workspace to save opportunities, review their
requirements, and track progress. Every user sets their own preferences. No
person's CV, credentials, or real applications are included in the repository.

## Features

- Separate accounts, jobs, and preferences for every user.
- Add, edit, delete, and immediately undo deletion of a job.
- Board/list views, search, and stage/job-type filters.
- Saved, Applied, Interview, Offer, Rejected, and Withdrawn stages.
- Original application dates, stage history, and private notes.
- Explained matches, gaps, and unknowns for skills, location, work arrangement,
  job type, language, German level, office days, and commute preferences.
- Review suggested fields from pasted descriptions before saving.
- JSON import/export compatible with the original CLI; no silent overwrites.
- Clearly marked fictional samples, plus the original offline add/list CLI.

- Search ten selected job/university sources using a private search profile.
- View source failures, explained relevance, cached results, and local usage limits.

## Quick start

Requires **Python 3.10+** with SQLite support. Download and extract the repository
ZIP, or clone it:

```sh
git clone https://github.com/Rostamnezhad/agentic-job-tracker.git
cd agentic-job-tracker
```

**Windows PowerShell** — no environment activation needed:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m job_tracker serve
```

**macOS / Linux:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m job_tracker serve
```

Open **http://127.0.0.1:8000**. Create a username and a password with at least
12 characters. Save your password: email recovery is not implemented. Choose
**Explore with sample jobs**, or add your first opportunity.

Use the Python executable inside `.venv` for subsequent commands, or activate
the environment first. Stop the server with **Ctrl+C**; your data stays on disk.
Internet access is needed to install dependencies; ordinary tracking works
offline. No Node.js build is needed. Only optional live discovery requires an API key.

## Search setup

1. Create a **free Researcher account** at [Tavily](https://app.tavily.com) and obtain
   its API key. Keep paid plans and pay-as-you-go disabled. Never paste the key into
   chat, a GitHub issue, source code, or a command containing the literal key.
2. Stop your running server with Ctrl+C, then run from the project folder:

   ```powershell
   .\.venv\Scripts\python.exe -m job_tracker serve --ask-search-key
   ```

   On macOS/Linux: `.venv/bin/python -m job_tracker serve --ask-search-key`.
   The terminal prompts privately; typing/pasting is hidden. Press Enter when done.
   The key lasts only for this server process. Alternatively, supply the server's
   `TAVILY_API_KEY` environment variable through your host's secret configuration.
3. Open the app, select **Find jobs**, enter skills, interests, languages/levels,
   town, country, job type and maximum distance in kilometres. Save the profile.
4. Choose sources, then click **Search selected sources**. A search can take about
   a minute. Check each source's status and each lead's unknowns. **Review and save**
   opens an editable draft; you must verify and enter the employer before saving.

The current Germany-focused source catalogue is LinkedIn, Indeed, StepStone,
Bundesagentur für Arbeit, Arbeitnow, Jobicy, RPTU, Studierendenwerk Kaiserslautern,
academics, and Jobmensa. These are selected sources, not a measured “top ten.”
University coverage is currently specific to Kaiserslautern, not every university.

### Free-plan controls and limits

As checked on 2026-11-24, Tavily offers 1,000 free credits/month without a credit
card. A basic search costs one credit. Ten sources use ten requests, giving
roughly 100 full searches within that allowance if nothing else uses the key.
See [current provider pricing](https://docs.tavily.com/documentation/api-credits).

- Every request explicitly selects `basic`; automatic parameter upgrades are off.
- No extraction, crawling, research, LLM, automatic retries, or paid fallback.
- Hard local cap: 1,000 reserved requests per UTC calendar month across this
  installation; 40 requests per account in a rolling 24-hour period.
- Reservations are committed before network access, so concurrent calls cannot
  bypass the cap. Failures still count conservatively toward the local limit.
- Identical profiles reuse successful/partial results for 24 hours without new
  requests. Entirely failed runs can be retried after fixing configuration.
- Counts belong to this database, not your entire Tavily account. Other apps or
  installations can consume credits too. Restoring an old database backup can
  roll back local counters. The provider dashboard is authoritative for billing.
- The app cannot inspect or change your Tavily billing plan. Remaining free on
  Tavily is essential: a local cap cannot guarantee zero charges on a paid account.

### What discovery does and does not verify

The search profile is sent to Tavily along with each chosen domain. Account names,
passwords, existing applications and private notes are not included. The key stays
on the server and is never returned to the browser. A shared deployment uses one
server key; all users share its local monthly budget.

Discovery searches public indexed pages through Tavily; it does not directly
scrape or sign into LinkedIn/Indeed. Coverage is incomplete and search results can
include listing pages, closed roles, or outdated information. “No results” is not
proof that a source has no suitable jobs. Result URLs are restricted to their
requested source and deduplicated after removing common tracking parameters;
different URLs for the same vacancy may remain.

**Distance is currently a search-query preference, not a verified radius filter.**
No geocoder or route service is called. A town mention does not prove the office
location, and results outside the requested radius can appear. Required languages,
levels and current availability also remain unverified. Keyword points rank
mentions of skills, interests, town and job type; they are not match percentages
or hiring probabilities. They do not understand negation or synonyms. Live use
requires your key; automated tests use deterministic provider fixtures, not live
Tavily results.

### Updating an existing ZIP installation

Stop the server, download the latest repository ZIP and extract it into a **new
folder**. Recreate `.venv` and install `requirements.txt` there. The default web
database lives in your home directory, outside the source folder, so existing
accounts/jobs remain available. If you used `--web-db`, back up that file and keep
using the same path. New discovery tables are created automatically without
changing existing jobs. Do not overwrite or delete your database.

If `py` is not on PATH but you have Anaconda, run its Python executable to create
the virtual environment, for example:

```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m venv .venv
```

## Example: tracking a working-student application

1. Open **My preferences**. Choose Working student and your working language.
   Set your skills, preferred cities, German level, work arrangement, maximum
   office days per week, and maximum one-way commute.
2. Choose **Import jobs** and paste a description. Explicit lines such as
   `Company: Example Labs`, `Role: Python Developer`, and
   `URL: https://example.com/jobs/python` can be extracted.
3. Review the draft and complete missing details. Travel times and office
   schedules stay unconfirmed until you enter information you have checked.
4. Save the job, inspect its preference check, and add private notes.
5. After you actually apply, change the stage to **Applied**. The date defaults
   to today in your browser. Later stage changes keep the original date.

Checks are literal comparisons, not assessments of hiring chances. Skill checks
find mentions in the title and description, including possibly negated mentions;
they do not prove that you meet every requirement. Remote jobs skip the preferred
city check; review country/residency conditions yourself. Structured language
checks currently support English, German, or both; use notes for other languages.
The importer reads pasted text and never fetches the job URL.

## MVP success criteria

| Criterion | Verification |
| --- | --- |
| Start the web app without API keys | Quick start or Docker |
| Accounts cannot access each other's jobs or preferences | Account-isolation API tests |
| Company, role, URL, stage, and date persist after restart | `examples/web_demo.py` |
| Editing preserves dates and records stage changes | History tests and browser workflow |
| Stale edits cannot overwrite newer changes silently | Version-conflict tests |
| Invalid/duplicate imports cannot partially change a job list | Atomic import tests |
| Deletion can be immediately undone | API tests and browser workflow |
| Unknown requirements remain unknown and checks explain results | Intake tests |
| Original CLI remains functional | Original 14 tests and CLI demo |
| Personal data and credentials stay out of commits | `.gitignore` and fictional samples |

## Model and persistence

| Field | Rule |
| --- | --- |
| Company, role | Required, nonblank text |
| URL | Absolute HTTP(S), without credentials, whitespace, or control characters |
| Stage | `saved`, `applied`, `interview`, `offer`, `rejected`, `withdrawn` |
| Original application date | Real `YYYY-MM-DD`; absent for Saved, required for other stages |
| Location, description, notes | Optional text with length limits |
| Work arrangement, type, language, German level | Explicit choices; default is unconfirmed |
| Office days, one-way commute | Optional integers: 0–5 days/week and 0–600 minutes |
| ID, timestamps, version, history | Server-maintained |

Exact URLs are unique among an account's active jobs; different URLs for the same
vacancy are not merged. Moving a job back to Saved clears its application date.
Deletion hides an entry from lists and exports but retains it in the database
for recovery. Undo remains available until its notification is dismissed or replaced.

The web database defaults to `~/.agentic-job-tracker/web.sqlite3`. Customize it:

```sh
python -m job_tracker serve --web-db data/web.sqlite3 --port 8000
```

The original CLI has a separate `~/.agentic-job-tracker/jobs.sqlite3`; it does not
bypass web accounts. Transfer CLI entries by importing its JSON output through
**Import jobs → Choose JSON file**. JSON must be UTF-8. The browser accepts up to
200 records and 900 KB. Duplicate URLs reject the entire batch; use an empty
account or remove duplicates from the import file first. Exports include current
job details, not passwords, preferences, or stage history.

For a complete backup, stop the server and copy its SQLite file to a private
location. Databases are unencrypted files on the host machine. JSON exports
include private notes; save them inside an ignored folder such as `data/`.

## Original offline CLI

`add` and `list` still require only Python's standard library:

```sh
python -m job_tracker add --company "Example Labs" --role "Python Developer" --url "https://example.com/jobs/python"
python -m job_tracker add --company "Example AI" --role "Junior AI Engineer" --url "https://example.com/jobs/ai" --status applied --applied-date 2026-11-23
python -m job_tracker list
python -m job_tracker list --status applied
python -m job_tracker list --json
python -m job_tracker --db data/jobs.sqlite3 list
```

Put `--db` before `add` or `list`. Applied defaults to today's date; other nonsaved
stages require `--applied-date` explicitly. Exit codes: 0 for success, 2 for
invalid input/duplicates, 1 for database/filesystem errors. All example companies
and job URLs in this repository are fictional.

## Tests and end-to-end examples

After installing `requirements.txt`:

```sh
python -m unittest discover -s tests -v
python examples/demo.py
python examples/web_demo.py
```

The suite covers models, real CLI subprocesses, persistence, account separation,
password hashing, session expiry/logout, CSRF/origin checks, rate limits,
validation, conflicting edits, history, undo, import/export, and preference checks.

The web demo starts the real Waitress HTTP server with temporary data. It creates
two fictional accounts, sets preferences, reviews an import, saves/updates a job,
checks isolation, exports/imports, deletes/restores, then restarts the server and
verifies persistence. Both demos print `PASS` and remove their temporary files.

Without web dependencies, run only the original suite:
`python -m unittest tests.test_tracker -v`.

## Running on a server

This is runnable source, not a hosted public service. GitHub Pages cannot run
its Python backend. Use a machine or container host with persistent storage.
The `serve` command runs Waitress, not Flask's development server.

```sh
docker build -t agentic-job-tracker .
docker run --rm -p 127.0.0.1:8000:8000 -v job-tracker-data:/data agentic-job-tracker
```

The named volume keeps data after the container stops. For internet access,
put an HTTPS reverse proxy in front of the app and restrict backend access to
that proxy. Configure the following on the server:

| Environment variable | Purpose |
| --- | --- |
| `JOB_TRACKER_WEB_DB` | Persistent SQLite file; overridden by `--web-db` |
| `JOB_TRACKER_HTTPS=1` | Secure session cookies and HSTS on HTTPS deployments |
| `JOB_TRACKER_ALLOWED_HOSTS` | Comma-separated public hostnames, without scheme/path |
| `JOB_TRACKER_PROXY_IP` | Exact IP of one trusted reverse proxy, for the `serve` command |

Set a trusted proxy IP only for a proxy you control. It must overwrite forwarded
headers and supply the external host/scheme. Direct deployments leave this
unset. Do not enable secure cookies when using plain HTTP locally.

Passwords use scrypt hashing. Sessions have random server-stored tokens, seven-day
expiry, HttpOnly/SameSite cookies, and CSRF protection; logging out revokes that
session. Login/registration attempts are limited per IP or username. Database
queries are parameterized and every record operation checks the owner. User text
renders as text under a restrictive Content Security Policy.

This is a small-app MVP. Account recovery/deletion, MFA, an administrative interface,
high-availability storage, and a production security review remain future work.
Operators can access their server's database; account isolation is not end-to-end
encryption. Never publish the database or personal exports with the source.

## Structure and contributions

| Path | Responsibility |
| --- | --- |
| `job_tracker/models.py` | Shared validated job-entry model |
| `job_tracker/storage.py`, `cli.py` | Original CLI storage/commands and web launcher |
| `job_tracker/workspace.py` | Accounts, sessions, web jobs, versions, history |
| `job_tracker/discovery.py` | Tavily adapter, profiles, ranking, cache and quota reservations |
| `job_tracker/intake.py` | Reviewed extraction and preference checks |
| `job_tracker/web.py` | Flask API, authorization, validation, headers |
| `job_tracker/templates/`, `static/` | Responsive board/list interface and forms |
| `tests/`, `examples/` | Regression tests and reproducible demos |

Contributions are welcome: open an issue describing a user problem, then a focused
pull request with relevant tests. Keep real applications, CVs, databases, exports,
and secrets out of commits.

Next milestones: an optional local-model extraction adapter with an evaluation
dataset, verified geographic filtering, user-reviewed CV matching, and opt-in reminders. Future
agents should propose actions for review and keep uncertain facts explicit.

Licensed under the [MIT License](LICENSE).
