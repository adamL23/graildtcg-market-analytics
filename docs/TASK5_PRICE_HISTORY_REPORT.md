# Task 5 — Price-History Ingestion Report

## Objective

Task 5 implemented repeatable price-history ingestion for the 489 cards loaded
during Task 4. It retrieves all available TCGAPI.dev history for the four
verified catalogs, validates the provider data, preserves raw evidence, and
upserts one canonical observation per card, provider, printing, currency, and
date.

Gem Pack Vol. 6 and Japanese OP-17 remain unresolved and were not substituted
with data from another language or provider.

## Developed components

| Component | Purpose | Output and expected result |
|---|---|---|
| `config/history_ingestion.json` | Declares the four source-set keys, 489 expected cards, USD mapping, full-history range, 50-card batch size, and four request workers. | Configuration validation must fail before API access if a required value or expected catalog count is incorrect. |
| `src/gmad/tcgapi_client.py` | Adds authenticated access to `GET /v1/bulk/history` and Decimal-aware JSON parsing. | Returns both the parsed response and exact response text without logging or saving the API key. Requests contain no more than 50 card IDs. |
| `src/gmad/history_ingest.py` | Selects configured cards, downloads batches, validates observations, calculates normalized SHA-256 hashes, classifies provider-omitted cards, and performs the canonical database upsert. | New observations are inserted, changed observations are revised, unchanged observations are left untouched, and previously stored observations absent from a later response are retained. |
| `scripts/sync_price_history.py` | Provides the Task 5 command-line entry point and creates a timestamped run. | Prints requested-card, coverage, inserted, revised, unchanged, retained, and database-row totals, followed by the manifest path. |
| `sql/005_widen_price_precision.sql` | Widens the three price columns from `NUMERIC(12,2)` to `NUMERIC(14,4)`. | Four-decimal provider values such as `0.1324` are stored without rounding while retaining the original ten-digit integer capacity. |
| `sql/verify_price_history_load.sql` | Performs read-only post-load integrity and coverage checks. | Reports per-set coverage and date ranges, missing-history cards, duplicate keys, orphans, NULL/zero counts, negative values, and source/currency/printing totals. |
| Raw batch snapshots and `manifest.json` | Preserve provider evidence and the result of each completed run. | Each successful run contains ten raw batch files plus a manifest with coverage, duplicate, revision, omission, and load counts. No credential material is present. |
| `README.md` and `PROJECT_PROGRESS.md` | Document execution, design decisions, verified results, and project status. | A new developer can reproduce the migration, ingestion, verification, and idempotency check in the correct order. |

## Verified outputs

The initial successful run produced these results:

- 489 cards requested across four verified sets.
- 488 cards with history and one card without provider history.
- 117,828 canonical price-history rows inserted.
- Four printing categories: `Normal`, `Foil`, `Holofoil`, and
  `Reverse Holofoil`.
- Explicit source/currency mapping of `tcgapi.dev` and `USD`.
- Zero orphan rows, duplicate canonical groups, conflicting duplicates, or
  negative numeric rows.
- Provider `NULL` values remained SQL `NULL`; zero-valued observations remained
  zero.

The one card without history is TCGAPI card `2185531`, Monkey.D.Luffy
`EB04-061 (SP)`. Its individual history request succeeded with HTTP 200 and an
empty `data` object. It is therefore classified as provider-omitted/no-history,
not as a failed request.

An immediate second run confirmed idempotency:

- 0 rows inserted.
- 0 rows revised.
- 117,828 rows unchanged.
- 117,828 rows remained in the database.

## Key engineering challenges

### Live API limit differed from the earlier reference

The live endpoint rejected 100 IDs with HTTP 400 and stated a maximum of 50.
The loader and configuration now enforce the live 50-ID limit and use ten
batches for the current catalog.

### Source precision exceeded the original schema

Pre-write validation found a four-decimal market price (`0.1324`). Loading it
into `NUMERIC(12,2)` would have silently rounded the value. Migration `005`
widened all price columns to `NUMERIC(14,4)`, and Python validation rejects any
future value that exceeds this scale rather than silently losing precision.

### A successful response can omit a requested card

The bulk endpoint can return HTTP 200 without a key for a valid card that has no
history. An individual request confirmed this behavior for card `2185531`. The
loader records these IDs in the manifest and counts them as no-history coverage,
while continuing to reject malformed responses and unrequested card IDs.

### High observation volume required efficient loading

The full snapshot contained 117,828 observations. Four concurrent read-only API
requests reduce retrieval time, and validated rows are sent through PostgreSQL
`COPY` into a transaction-local staging table before one canonical upsert. This
keeps the load atomic and avoids slow row-by-row inserts.

### Idempotency and provider revisions required different handling

Each normalized observation receives a SHA-256 hash. The canonical key controls
uniqueness, while the hash distinguishes an unchanged repeat from a provider
revision. Changed rows can be updated with revision details in the manifest;
unchanged rows are not rewritten, and historical rows missing from a later
response are never deleted automatically.

## Expected operating result

For an unchanged provider snapshot, every subsequent run should report zero
inserted and revised rows, with all current observations classified as
unchanged. New dates should be inserted, genuine revisions should be updated and
logged, and transient omissions should not erase previously loaded history.

