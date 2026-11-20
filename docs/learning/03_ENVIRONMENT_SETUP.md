# Chapter 3 — Development Environment Setup

## Install and create the project environment

The verified local stack used Python 3.14, PostgreSQL 17, VS Code, Git, and Power
BI Desktop on Windows. A similar installation can use a supported current Python
3 release, but dependency compatibility should be retested.

From PowerShell in the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:PYTHONPATH = (Resolve-Path .\src)
```

The project used `.venv\Scripts\python.exe` explicitly because the generic
Windows `python` alias did not launch the installed runtime reliably.

## Directory structure

```text
config/          Non-secret allowlists and ingestion policies
data/raw/        Timestamped provider evidence and manifests
docs/            Task reports and this learning guide
scripts/         Executable command-line entry points
sql/             Forward migrations, verification, rollback-only tests
src/gmad/        Reusable Python package
.env.example     Safe credential template
requirements.txt Minimal Python dependencies
```

## Configure environment variables safely

Copy `.env.example` to `.env` and replace placeholders locally:

```dotenv
PGHOST=localhost
PGPORT=5432
PGDATABASE=graildtcg
PGUSER=graildtcg_app
PGPASSWORD=replace_me
TCGAPI_KEY=replace_me
```

Never commit `.env`. `src/gmad/config.py::DatabaseSettings.from_environment`
requires database, user, and password, rejects placeholders, and converts
`PGPORT` to an integer. `TcgApiClient.__init__` separately validates
`TCGAPI_KEY`. Neither prints a secret.

## Bootstrap and smoke test

Initial bootstrap is a one-time administrative operation:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\bootstrap_database.py
.\.venv\Scripts\python.exe -m gmad.smoke_test
```

`bootstrap_database.py::names_are_available` refuses to alter an existing role
or database. `main` generates a random password, creates `graildtcg_app` with no
superuser/database/role/replication privileges, creates the UTF-8 database, then
updates ignored `.env` without displaying the password.

`src/gmad/smoke_test.py::main` runs `version()`, `current_database()`,
`current_user`, and `SELECT 1`. It separates configuration errors from Psycopg
connection errors.

## Apply SQL safely

```powershell
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\001_create_core_tables.sql
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_core_schema.sql --read-only
```

`scripts/run_sql_file.py::sql_path` permits only `.sql` files inside the project
`sql/` directory. `--read-only` asks PostgreSQL to reject mutations.

## Git workflow

Initialize and make small, reviewable commits if the folder is not already a
repository:

```powershell
git init
git add .gitignore requirements.txt src scripts sql config docs
git status
git commit -m "Document Phase 1 pipeline"
```

Inspect `git status` before every commit. Never add `.env`, `.env.powerbi`, raw
credentials, `.venv`, or generated caches.

## Exercise

Temporarily set `PGPORT=not-a-number` in a disposable environment and run the
smoke test. Read the error from `DatabaseSettings.from_environment`, then restore
the correct value. This demonstrates failing before a network connection.

Expected outcome: [exercise answer key](16_EXERCISE_ANSWER_KEY.md#chapter-3--environment-setup).

