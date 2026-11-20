# Learning Roadmap and Source Audit

## What was audited

The guide was written after inspecting the implementation rather than relying
only on project summaries. The source-of-truth inventory is:

| Area | Implemented files |
| --- | --- |
| Shared Python | `src/gmad/config.py`, `db.py`, `smoke_test.py`, `tcgapi_client.py` |
| ETL modules | `catalog_ingest.py`, `history_ingest.py`, `current_price_ingest.py`, `condition_price_ingest.py`, `graded_price_ingest.py`, `reported_sale_ingest.py` |
| Entry points | Nine scripts under `scripts/`, including the six sync commands, SQL runner, database bootstrap, and Power BI role setup |
| Schema | Migrations `sql/001_...` through `sql/010_...` |
| Tests | `sql/verify_*.sql` and rollback-only `sql/test_*.sql` |
| Configuration | Six ingestion JSON files plus resolved and example target-set allowlists under `config/` |
| Evidence | Timestamped raw runs and manifests under `data/raw/` |
| Decisions | `README.md`, `PROJECT_PROGRESS.md`, `POST_MVP_IMPROVEMENTS.md`, and Task 4–10 reports under `docs/` |

The installed Python dependencies are deliberately small: Psycopg 3,
python-dotenv, and Requests (`requirements.txt`). PostgreSQL 17 and Power BI
Desktop are external tools rather than Python packages.

## Implemented Phase 1 boundary

Implemented and verified:

- four available set catalogs and 489 cards;
- 117,828 historical price observations;
- 489 latest current-price rows;
- 1,219 condition-price rows;
- 1,264 graded summary rows;
- 12,568 reported-sale observations in one completed snapshot;
- six read-only reporting views and a Power BI Import model.

Not implemented:

- an alternative provider for Simplified Chinese Gem Pack Vol. 6 or Japanese
  OP-17;
- orchestration, scheduled jobs, cloud hosting, monitoring/alerts, or a Power BI
  gateway;
- cross-snapshot sale deduplication, stable transaction identity, scraping,
  seller analytics, grade normalization, or production dashboard visuals.

## Evidence gaps and careful language

The repository contains local/manual operating commands. It does not contain a
production scheduler or a definitive weekly individual-sale runbook. Public
coverage JSON includes provider refresh categories such as `weekly`, but that is
provider metadata—not a GraildTCG schedule. Chapter 12 therefore presents a
weekly cadence only as a **proposed future policy**.

Likewise, reported-sale rows are observations returned by TCGAPI.dev, not
verified unique eBay transactions. No stable sale ID, currency field,
pagination token, total count, or time-of-day was observed.

## Learning outcomes

After completing the guide you should be able to:

1. design normalized operational tables and analytical views;
2. call and validate a paginated or batched REST API;
3. preserve exact raw evidence and provenance;
4. build idempotent, timestamp-aware PostgreSQL loads;
5. distinguish snapshots, history, aggregates, and observations;
6. test constraints and data quality without contaminating production rows; and
7. expose data through a least-privilege Power BI star schema.

## Comprehension check

Why is a raw JSON file not a substitute for a database table, and why is a
database table not a substitute for the raw file? Write two reasons for keeping
both before continuing.

Compare your answer with the [exercise answer key](16_EXERCISE_ANSWER_KEY.md#learning-roadmap).

