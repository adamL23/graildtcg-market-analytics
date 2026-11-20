# Task 7 — Condition-Level Pricing Report

## Objective

Task 7 adds the latest available cached condition-level TCGPlayer listing prices
for the 489 cards loaded in Task 4. It does not include graded prices, eBay
sales, supply analytics, or automatic per-card cache warming.

## Verified provider behavior

TCGAPI documents `GET /v1/bulk/conditions` as a cache-only endpoint for up to
500 cards. Cards without cached condition data are omitted, while per-card
condition requests can trigger quota-bounded refreshes:

- https://tcgapi.dev/llms-full.txt
- https://tcgapi.dev/introduction

The preserved discovery response returned 1,219 rows covering all 489 requested
cards. Real data contained:

- Conditions: Near Mint, Lightly Played, Moderately Played, Heavily Played,
  Damaged, and Unopened.
- Listing languages: English and Japanese.
- Printings: Normal, Foil, Holofoil, and Reverse Holofoil.
- Provider timestamps spanning several cache-refresh times.
- Seventy shipping-inclusive values with more than four decimal places due to
  provider floating-point artifacts.

Because `Unopened` appears in the live response, the database validates
condition labels as nonblank provider text rather than enforcing an incomplete
five-value enum.

## Developed components

| Component | Purpose |
|---|---|
| `config/condition_price_ingestion.json` | Declares the four canonical set keys, 489-card expectation, USD mapping, 500-card batch size, and disabled cache warming. |
| `sql/007_create_condition_prices.sql` | Creates the latest-snapshot table, canonical key, checks, indexes, timestamps, provenance, and card relationship. |
| `src/gmad/condition_price_ingest.py` | Fetches the bulk cache, preserves exact raw JSON, validates rows, hashes snapshots, records omissions, and performs timestamp-guarded upserts. |
| `scripts/sync_condition_prices.py` | Runs extraction, validation, loading, manifest creation, and the console checkpoint summary. |
| `sql/verify_condition_price_load.sql` | Verifies coverage, integrity, values, sample/median behavior, dimensions, and prior-task row counts. |
| `sql/test_condition_price_constraints.sql` | Rollback-only test for zero and NULL preservation plus negative price and sample rejection. |

## Snapshot semantics

The canonical key is:

```text
card_id + source_name + currency_code + printing + condition_name + listing_language
```

`provider_observed_at` maps `last_updated_at`; `loaded_at` records PostgreSQL
ingestion. Newer provider observations replace the stored row, changed data at
the same timestamp is treated as a provider revision, and older observations
are skipped. Rows absent from a later cache response are retained.

Price columns use `NUMERIC(30,16)` to preserve the exact JSON values without
silent rounding. `sample_count` is a sampled-listing count, not total market
depth. `median_with_shipping` remains NULL when the provider has fewer than
three samples.

## Verified results

- 489 cards requested and 489 cards covered.
- 1,219 canonical condition rows inserted.
- Set coverage: Pitch Black 432 rows, OP-17 English 371, Mega Brave 203, and
  Mega Symphonia 213.
- 345 NULL shipping medians, all associated with sample counts below three.
- Sample counts ranged from 1 to 50.
- Zero orphan rows, duplicate canonical keys, negative values, timestamp-order
  violations, or median/sample inconsistencies.
- Current-price rows remained at 489 and historical rows at 117,828.

A direct stale-input test submitted an altered row with an older provider
timestamp. It was counted as skipped and its stored hash remained unchanged.

The immediate second complete run confirmed idempotency: zero inserts, zero
updates, zero same-timestamp revisions, and 1,219 unchanged rows.

## Expected future behavior

Routine runs should load the available rolling cache without consuming per-card
refresh allowances. If a future response omits a card, the manifest will report
the missing cache coverage and the database will retain the last accepted
snapshot. Cache warming can be designed separately around an explicit watchlist
and refresh budget.

