# GraildTCG Market Analytics Dashboard

Local learning project for loading TCG API data into PostgreSQL and analysing it in Power BI.

## Task 1: database connection smoke test

From Windows PowerShell in this directory:

```powershell
Copy-Item .env.example .env
# Edit .env and replace PGPASSWORD with the local PostgreSQL password.
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe -m gmad.smoke_test
```

Expected output identifies the PostgreSQL server, database, user, and prints `SELECT 1: 1`.
No database tables are created by this command.

## Task 2: dedicated database and role

The one-time bootstrap creates the `graildtcg` database and the restricted
`graildtcg_app` login. It generates the application password locally, does not
print it, and switches `.env` from the bootstrap superuser to the application login.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\bootstrap_database.py
.\.venv\Scripts\python.exe -m gmad.smoke_test
```

The bootstrap refuses to change pre-existing database or role objects with the
same names. Run it only once.

## Task 3: core schema

The original `001` migration is the applied baseline. Forward-only migrations
`002` and `003` revise and normalize that empty schema without dropping or
recreating existing tables.

For a database where `001` and `002` are already applied, apply `003`, run the
expanded read-only verification, then execute the synthetic constraint tests
(the test file ends with `ROLLBACK`):

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\003_add_sets_table.sql
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_core_schema.sql --read-only
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\test_core_constraints.sql
```

The normalized relationship is `sets (1) -> cards (many) -> price_history
(many)`. `cards.set_id` is the GraildTCG internal foreign key; provider set ID,
game, language, region and release metadata live once in `sets`.

`sets.source_set_key` is a stable ETL/configuration identity, not a provider
field. It prevents name-only matching and provides an identity when no TCGAPI.dev
set ID exists. The example target allowlist is kept separately in
`config/target_sets.example.json`. Unverified regional catalog references must be
resolved to a canonical key before ETL creates set or card records.

`cards.tcgapi_card_id` is the stable provider identity. `price_history.card_id`
is a foreign key to the internal card identity. `variant_name` is an optional,
normalized card-identity label; `printing` is the provider's price category.

One canonical historical row is stored per card, provider, printing, currency,
and observation date. If a provider revises that date, ETL will compare
`source_record_hash` and update the canonical row. The raw response and ETL log
must record the change; full revision-history tables are deferred beyond Phase 1.

### Validation boundary

PostgreSQL enforces required values, keys and relationships, nonblank provider
labels, positive identifiers, nonnegative numeric values, uppercase three-letter
currency codes, SHA-256 format, and canonical daily uniqueness.

Python ETL will validate response shapes, parse dates and decimals, map the
provider and currency from verified endpoint metadata, derive optional identity
variants, normalize hashes, retain raw responses, and log provider revisions.
Missing numerical fields remain `NULL`; Python must not replace them with zero.

## Task 4: target-set catalog ingestion

`config/target_sets.json` holds provider resolutions separately from the schema.
Regional references that resolve to the same canonical TCGAPI set key are fetched
and loaded once. Unresolved or unavailable targets are reported and skipped.

OP-17 English resolves to TCGAPI set `1100079` (`The World's Strongest
Warriors`). TCGAPI.dev currently exposes no separately identifiable Japanese
OP-17 game/set catalog; that target remains configured with no provider ID and is
skipped. Set `1100086` is the English Release Event catalog and is not treated as
a Japanese edition.

The complete language-specific discovery results, page counts, request outcomes,
and missing-coverage classification are recorded in
`docs/TASK4_SET_COVERAGE.md`.

The loader requests only `type=Cards`; sealed products are outside this checkpoint.
Each provider response is preserved under a timestamped `data/raw/tcgapi` run
directory before the validated rows are upserted in one database transaction.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\004_allow_missing_card_number.sql
.\.venv\Scripts\python.exe .\scripts\sync_target_catalogs.py
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_catalog_load.sql --read-only
```

The project `.env` must contain `TCGAPI_KEY`. The key is never written to raw
snapshots, manifests, logs, or database rows.

## Task 5: canonical price-history ingestion

The history loader requests TCGAPI.dev's bulk history endpoint in batches of at
most 50 cards, matching the live endpoint's enforced limit. Four read-only
requests may run concurrently; validated rows then use a temporary PostgreSQL
`COPY` stage before the canonical upsert. Its default history endpoint is
TCGPlayer-sourced, so Task 5 maps
these observations explicitly to `USD`; the separate Cardmarket endpoint is not
used. Provider `NULL` values remain SQL `NULL` and are never converted to zero.

Each exact response and a run manifest are retained in a timestamped
`data/raw/tcgapi_history` directory. A normalized SHA-256 hash distinguishes new,
unchanged, and revised canonical observations. Revised rows are updated, while
older database observations absent from a later response are retained.
The live endpoint can return HTTP 200 with no map entry for a valid card that has
no history; those IDs are recorded in the manifest as provider-omitted and are
counted as cards without history, not as request failures.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\005_widen_price_precision.sql
.\.venv\Scripts\python.exe .\scripts\sync_price_history.py
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_price_history_load.sql --read-only
```

Migration `005` widens the three price columns from `NUMERIC(12,2)` to
`NUMERIC(14,4)`. The live history feed includes four-decimal values, so this
forward-only change prevents PostgreSQL from silently rounding source data while
retaining the original ten-digit integer capacity.

Run the loader a second time to verify idempotency: an unchanged provider
snapshot should report zero inserted or revised rows.

## Task 6: current market snapshots

The current-price loader reuses the existing TCGAPI set-card endpoint because
those card responses already contain the required current-price fields. It does
not depend on a separate current-price endpoint. One latest snapshot is stored
per card, provider, currency, and printing.

`market_price_as_of` is the provider's date for the market-price value,
`provider_observed_at` maps the provider's `price_updated_at` timestamp, and
`loaded_at` records database ingestion. An incoming observation can update a row
only when its provider timestamp is newer, or when the provider revises data at
the same timestamp. Older observations cannot overwrite newer snapshots.

Provider `NULL` and zero values are preserved. `market_price_is_zero` flags a
reported zero for later analytical review without interpreting it as a genuine
zero-dollar valuation. Exact raw responses and a run manifest are retained under
`data/raw/tcgapi_current`.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\006_create_current_prices.sql
.\.venv\Scripts\python.exe .\scripts\sync_current_prices.py
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_current_price_load.sql --read-only
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\test_current_price_constraints.sql
```

Run the loader a second time to confirm that an unchanged provider snapshot
reports zero inserts or updates.

## Task 7: condition-level pricing snapshots

The condition-price loader uses `GET /v1/bulk/conditions` for all 489 configured
cards in one cache-only request. It does not call the per-card endpoint and does
not warm missing cache entries. Provider-omitted cards are recorded as missing
condition coverage rather than being interpreted as cards with no listings.

One latest row is stored per card, provider, currency, printing, condition, and
listing language. `provider_observed_at` maps the provider's `last_updated_at`,
while `loaded_at` records database ingestion. Newer observations and documented
same-timestamp revisions can update a row; older observations are skipped.

Condition labels remain validated provider text rather than a hard-coded enum.
The live response includes `Unopened` in addition to the five standard card
conditions. `sample_count` is the number of sampled listings, not total market
depth, and `median_with_shipping` is normally NULL below three samples.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\007_create_condition_prices.sql
.\.venv\Scripts\python.exe .\scripts\sync_condition_prices.py
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_condition_price_load.sql --read-only
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\test_condition_price_constraints.sql
```

Run the loader a second time to confirm that an unchanged provider cache reports
zero inserts or updates.

## Task 8: provider-reported graded price summaries

Task 8 stores aggregated graded eBay sold-price summaries and labels them as
provider-reported, unverified, and potentially incomplete. It does not ingest
individual sold listings.

The workflow deliberately separates extraction from loading. `--fetch` checks
public set coverage, calculates projected credits, performs a quota probe, and
makes one full `include=ebay` bulk request only when the projected cost plus a
safety buffer fits. It saves raw JSON but does not write graded rows. Subsequent
`--replay-run` commands perform ETL entirely from that saved response and consume
no API credits.

Coverage metrics remain distinct: cards requested, cards with any eBay data, and
cards with actual graded summaries. `graded_days` measures the graded rolling
window; ungraded `days` is retained separately and is never substituted.
`median_30d` remains nullable independently of historical `last_sale_price` and
`last_sold_date`.

Rows absent from a newer accepted snapshot are retained with
`is_reported_in_latest_snapshot = false`. They are last-known observations, not
current 30-day valuations.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\008_create_graded_price_summaries.sql

# Credit-consuming extraction: run once after reviewing the quota projection.
.\.venv\Scripts\python.exe .\scripts\sync_graded_prices.py --fetch

# Replace RUN_ID with the fetch output. These commands make no API calls.
.\.venv\Scripts\python.exe .\scripts\sync_graded_prices.py --replay-run RUN_ID
.\.venv\Scripts\python.exe .\scripts\sync_graded_prices.py --replay-run RUN_ID

.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_graded_price_load.sql --read-only
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\test_graded_price_constraints.sql
```

Do not repeat `--fetch` merely to test idempotency; replay the preserved raw run.

## Task 9: provider-reported sale observations

Task 9 stores individual provider-returned eBay sale observations without
claiming that they are globally unique marketplace transactions. The immutable
replay key is source snapshot, internal card, printing, and the deterministic
one-based position in that printing's sales array. A conflicting hash for an
existing replay key is a data-integrity error; stored observations are never
silently overwritten.

Extraction is resumable and keeps one snapshot key across resumes. Successful
raw card responses are saved immediately and never requested again. The workflow
enforces provider quota headroom, a configurable hard credit ceiling, four-worker
concurrency, and bounded retries. Currency remains NULL because the verified
response supplies no sale currency.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\009_create_reported_sale_observations.sql

# Credit-consuming extraction: start once, then resume the same run if needed.
.\.venv\Scripts\python.exe .\scripts\sync_reported_sales.py --fetch
.\.venv\Scripts\python.exe .\scripts\sync_reported_sales.py --resume-run RUN_ID

# Offline-only, idempotent database replay.
.\.venv\Scripts\python.exe .\scripts\sync_reported_sales.py --replay-run RUN_ID
.\.venv\Scripts\python.exe .\scripts\sync_reported_sales.py --replay-run RUN_ID

.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_reported_sale_load.sql --read-only
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\test_reported_sale_constraints.sql
```

Dashboard queries must choose a completed snapshot explicitly. They must not add
observations across multiple extraction snapshots as though each row were a new
real-world sale.

## Task 10: Power BI reporting foundation

Migration `010_create_reporting_views.sql` creates a lightweight `reporting`
schema with one Cards dimension and five unaggregated market fact views. The
reported-sale view is pinned to completed snapshot
`tcgapi.dev:ebay_sales:20261118T035224841879Z`; observations from different
extractions are never combined automatically.

Power BI uses the dedicated `graildtcg_powerbi` login in Import mode. That role
can select only the six reporting views and cannot directly query operational
tables. Its generated local credential is stored in ignored `.env.powerbi`.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\010_create_reporting_views.sql
.\.venv\Scripts\python.exe .\scripts\configure_power_bi_role.py
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_reporting_views.sql --read-only
.\.venv\Scripts\python.exe .\scripts\configure_power_bi_role.py --verify-only
```

The saved Power BI model uses active one-to-many, single-direction relationships
from `reporting.dim_cards[card_id]` to each fact. All raw price fields default to
`Don't summarize`. Full connection, view-grain, relationship, row-count, and
manual-refresh results are documented in `docs/TASK10_POWER_BI_MODEL.md`.

## Security

`.env` is excluded by `.gitignore`. Do not commit database or API credentials.

