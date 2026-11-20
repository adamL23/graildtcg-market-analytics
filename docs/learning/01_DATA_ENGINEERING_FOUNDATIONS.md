# Chapter 1 — Data Engineering Foundations

## What data engineering does

Data engineering turns external, changing data into trustworthy structures that
other systems can query. A **pipeline** is the repeatable path from source to
destination. GraildTCG starts with semi-structured TCGAPI.dev JSON and ends with
relational PostgreSQL tables and reporting views for Power BI.

The work is not merely “download JSON.” The pipeline must answer: Which card is
this? Is this row newer? What does missing mean? Can the same file be replayed
without duplication? Where did this value come from?

## Core concepts mapped to GraildTCG

| Concept | Plain-English meaning | GraildTCG example |
| --- | --- | --- |
| Ingestion | Bringing data into the system | `TcgApiClient` sends authenticated GET requests |
| Transformation | Validating and reshaping data | `_optional_decimal` converts JSON numbers to `Decimal` |
| Loading | Writing trusted records | `load_history` stages rows with PostgreSQL `COPY` |
| Structured data | Fixed columns and constraints | `current_prices` has typed columns and a unique key |
| Semi-structured data | Objects/arrays whose fields may vary | Saved TCGAPI JSON responses |
| Batch processing | Processing a bounded group at once | History uses batches of at most 50 card IDs |
| Data quality | Evidence that data obeys expected rules | nonnegative price checks and orphan queries |
| Idempotency | Safe repetition with the same outcome | a second graded replay inserts zero rows |
| Lineage/provenance | Knowing where a value came from | `source_file`, `source_row_number`, hashes, timestamps |
| Grain | What exactly one row represents | one history row per card/source/printing/currency/day |

## ETL versus ELT

**ETL** means extract, transform, then load. GraildTCG follows ETL for its
operational tables: it fetches JSON, validates it in Python, and only then opens
the database load transaction. For example,
`src/gmad/catalog_ingest.py::fetch_catalogs` verifies every page and expected
card count before `load_catalogs` writes sets and cards.

**ELT** loads raw data first and transforms it inside a warehouse. GraildTCG does
not use a raw JSON column as its primary database landing zone. Instead, it
preserves raw responses on disk and loads validated relational records. The
reporting views are a small ELT-like final transformation performed in SQL.

## History, snapshots, aggregates, and observations

These are different data models:

- `price_history` appends daily facts. New dates add rows.
- `current_prices` keeps the latest provider snapshot for a canonical key.
- `graded_price_summaries` keeps provider aggregates and can retain an older
  grade as “last-known.”
- `reported_sale_observations` stores immutable rows inside one extraction
  snapshot without claiming global transaction identity.

Confusing these models causes serious errors. Overwriting history destroys
trends; appending snapshots forever without a snapshot key creates duplicates;
calling observations “transactions” claims evidence the provider did not give.

## Operational database versus warehouse/reporting layer

PostgreSQL `public` tables are the operational system of record for Phase 1.
They preserve exact provider values and load semantics. The `reporting` schema
exposes a star-shaped analytical surface. It is not a separate data warehouse,
but it demonstrates the separation of concerns: ingestion tables optimize
correctness; views optimize safe consumption.

## Common mistakes

- Treating missing, `NULL`, and zero as interchangeable.
- Using binary floating point for money without understanding artifacts.
- Letting a retry create duplicate rows.
- Assuming an HTTP 200 response means complete data.
- Building visuals before defining row grain.
- Logging credentials or embedding them in source code.

## Practical exercise

For each Phase 1 table, write one sentence beginning “One row represents…”.
Compare your answer with Chapter 4. If you cannot state the grain precisely, you
are not ready to choose a unique constraint or a Power BI relationship.

