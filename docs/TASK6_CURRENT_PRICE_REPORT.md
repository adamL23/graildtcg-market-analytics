# Task 6 — Current Market Snapshot Report

## Objective

Task 6 adds the latest provider-reported current market snapshot for every card
loaded in Task 4. It is intentionally limited to ungraded current pricing;
condition prices, graded summaries, reported eBay sales, and full pipeline
observability remain separate tasks.

## Verified source model

The existing `GET /v1/sets/{id}/cards` responses already include `printing`,
`market_price`, `low_price`, `median_price`, `lowest_with_shipping`,
`total_listings`, `market_price_as_of`, `price_updated_at`, and
`no_market_price_since`. Task 6 therefore reuses the existing set-card endpoint
instead of adding another production endpoint. TCGAPI documents these set-card
responses as cards with current prices and identifies its pricing as
TCGPlayer-sourced:

- https://tcgapi.dev/llms-full.txt
- https://tcgapi.dev/introduction

Live verification confirmed the saved response shape against current provider
data before migration `006` was finalized.

## Developed components

| Component | Purpose |
|---|---|
| `config/current_price_ingestion.json` | Declares the four canonical source sets, expected 489-card coverage, USD mapping, and pagination. |
| `sql/006_create_current_prices.sql` | Creates the canonical latest-snapshot table, checks, indexes, generated zero flag, timestamp fields, and foreign key. |
| `src/gmad/current_price_ingest.py` | Fetches and preserves raw pages, validates every field, hashes normalized snapshots, and performs timestamp-guarded upserts. |
| `scripts/sync_current_prices.py` | Runs the complete snapshot, load, manifest, and console summary workflow. |
| `sql/verify_current_price_load.sql` | Checks coverage, missing cards, duplicates, orphans, NULL/zero behavior, timestamp ordering, printings, currencies, and historical-row preservation. |

## Snapshot semantics

The canonical key is `(card_id, source_name, currency_code, printing)`.

- `market_price_as_of` is the provider date for the market-price value.
- `provider_observed_at` is the provider's `price_updated_at` timestamp and
  determines whether an incoming snapshot is newer.
- `loaded_at` is the separate PostgreSQL ingestion timestamp.
- A newer provider timestamp replaces the stored snapshot.
- A changed hash at the same provider timestamp is treated as a provider
  revision.
- An older provider timestamp is skipped.
- Missing rows never delete existing snapshots.

Prices use `NUMERIC(30,16)` because the real response included a
shipping-inclusive value of `1.6099999999999999`. This preserves provider data
without silent rounding. Reporting-layer rounding can be designed separately.

## Verified results

- Four sets and 489 configured cards requested.
- 489 canonical current-price snapshots loaded.
- Full card coverage with no omitted cards.
- Printing distribution: 199 Normal, 127 Holofoil, 91 Foil, and 72 Reverse
  Holofoil.
- One NULL market price and no zero market prices in the successful runs.
- One `no_market_price_since` indicator, preserved independently of its last
  reported price.
- Zero orphan rows, duplicate canonical keys, negative values, timestamp-order
  violations, or zero-flag mismatches.
- Existing historical pricing remained unchanged at 117,828 rows.

An explicit stale-input test submitted an altered observation with an older
provider timestamp. The loader reported one older row skipped, and the stored
record hash remained unchanged.

The immediate second complete run confirmed idempotency: zero inserts, zero
updates, zero same-timestamp revisions, and 489 unchanged snapshots.

## Expected future behavior

Routine runs should insert newly cataloged canonical keys, update snapshots only
when the provider timestamp advances, accept documented same-timestamp provider
revisions, and reject older data. A provider-reported market price of zero will
remain zero and set `market_price_is_zero = true`; it will be flagged for later
analysis rather than interpreted automatically as a genuine zero-dollar value.

