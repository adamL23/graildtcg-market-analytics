# Chapter 12 — Operating the Pipeline

## Safe execution order

Set the import path once per PowerShell session:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
$python = ".\.venv\Scripts\python.exe"
```

Apply migrations in numeric order only once, then run the pipelines in dependency
order:

```powershell
& $python .\scripts\sync_target_catalogs.py
& $python .\scripts\sync_price_history.py
& $python .\scripts\sync_current_prices.py
& $python .\scripts\sync_condition_prices.py
```

Each command creates a UTC run folder, raw files, and a manifest. Do not delete a
raw run merely because loading succeeded; it is the replay/audit evidence.

## Credit-consuming workflows

Graded pricing separates fetch from load:

```powershell
& $python .\scripts\sync_graded_prices.py --fetch
& $python .\scripts\sync_graded_prices.py --replay-run RUN_ID
& $python .\scripts\sync_graded_prices.py --replay-run RUN_ID
```

The second and third commands make no API request. The repeat is the idempotency
test.

Reported sales use three modes:

```powershell
& $python .\scripts\sync_reported_sales.py --fetch
& $python .\scripts\sync_reported_sales.py --resume-run RUN_ID
& $python .\scripts\sync_reported_sales.py --replay-run RUN_ID
```

Use `--resume-run` only for the same incomplete extraction. It preserves the
snapshot key and skips successful card files. Use `--replay-run` only after the
request manifest says `complete`.

## Manifest checklist

Before loading or reporting, check:

- run ID and completion status;
- requested, successful, omitted, empty-array, and failed counts;
- raw-file paths and source snapshot key;
- projected, reserved, reported, and remaining credits;
- inserted, updated/revised, unchanged, skipped, retained, and database totals;
- whether eligibility and expected card counts still match.

Do not treat a missing manifest, incomplete status, or quota exhaustion as a
completed zero-row dataset.

## Verification commands

```powershell
& $python .\scripts\run_sql_file.py .\sql\verify_catalog_load.sql --read-only
& $python .\scripts\run_sql_file.py .\sql\verify_price_history_load.sql --read-only
& $python .\scripts\run_sql_file.py .\sql\verify_current_price_load.sql --read-only
& $python .\scripts\run_sql_file.py .\sql\verify_condition_price_load.sql --read-only
& $python .\scripts\run_sql_file.py .\sql\verify_graded_price_load.sql --read-only
& $python .\scripts\run_sql_file.py .\sql\verify_reported_sale_load.sql --read-only
& $python .\scripts\run_sql_file.py .\sql\verify_reporting_views.sql --read-only
```

Run the relevant rollback-only `test_*.sql` after schema changes, not as a
replacement for post-load verification.

## Diagnosing failures

- Configuration error: inspect the named JSON field or `.env` placeholder.
- HTTP/authentication error: preserve response/error evidence; do not label it
  missing coverage.
- HTTP 429/5xx/network failure in Task 9: let bounded retry/resume handle it.
- Quota gate: stop; do not bypass the safety buffer or hard ceiling.
- Incomplete raw run: resume the same run if supported; never offline-load it as
  complete.
- Hash conflict in immutable sales: investigate source/file integrity; do not
  update the stored row silently.
- OneDrive lock: allow atomic persistence retries, then resume from saved files.

## Refreshing Power BI

First complete and verify PostgreSQL ETL. Then open the PBIX and choose Refresh.
Confirm the six view counts, relationship cardinalities, single-direction card
filtering, null currency, and current/last-known labels. A Power BI refresh
imports database state; it should never call TCGAPI.dev.

## Local workflow versus proposed production policy

Phase 1 implements manual local commands only. A sensible future policy could
run inexpensive catalog/current/history checks on a controlled schedule and a
credit-budgeted individual-sale extraction weekly for an approved eligibility
snapshot. That weekly cadence is **a proposal, not implemented repository
behavior**. It needs orchestration, run locking, quota forecasting, monitoring,
completed-snapshot promotion, and a new reporting-view migration.

The frontend should query PostgreSQL/reporting views. It should not spend API
credits or wait on provider calls for each user request. Background ingestion
and user-facing queries have different reliability and latency needs.

## Practice exercises

1. Write a recovery runbook for a Task 9 run that completed 470 of 481 cards
   before a network outage. Include CLI mode, stable invariants, manifest fields,
   and the gate for database replay.
2. Read a completed Task 9 manifest and distinguish baseline projected,
   pessimistically reserved, provider-reported, and safety-buffer credits.
3. A raw run is complete but its load manifest is absent. Decide whether to
   fetch, resume, replay, or refresh Power BI, and justify the order.

Solutions are in [Exercise answer key](16_EXERCISE_ANSWER_KEY.md#chapter-12--pipeline-operations).

