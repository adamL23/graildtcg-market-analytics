# Task 8 — Provider-Reported Graded Price Summary Report

## Objective and scope

Task 8 adds the latest provider-reported aggregated graded eBay sold-price
summaries. These records are unverified and potentially incomplete. Individual
sold listings, titles, URLs, and transaction-level ingestion remain outside this
task.

## Discovery and coverage

Public eBay coverage was saved for Pokémon, Pokémon Japan, and One Piece before
schema design. Four high-market-price representative cards—one from each loaded
set—were then requested with `include=ebay`.

Discovery verified:

- `graded_days` is separate from ungraded `days`.
- Grade labels are diverse provider text, including PSA, BGS, CGC, ACE, TAG,
  SGC, and generic labels.
- A grade can have `median_30d = null` and `sales_30d = 0` while retaining an
  older `last_price` and `last_sold`.
- `include=ebay` returns aggregated summaries without individual sold listings.

The full extraction produced three distinct coverage metrics:

- 489 cards requested.
- 481 cards with any eBay data.
- 169 cards with actual graded summaries.

General eBay coverage is therefore not treated as graded-card coverage.

## Credit-controlled extraction

Public set coverage projected 481 cards with eBay data. The documented credit
formula produced a 482-credit projection: one base credit plus one for each card
with eBay data.

The quota probe reported 9,988 remaining daily credits. With the configured
100-credit safety buffer, the request fit safely. Exactly one full bulk request
was performed and its manifest recorded:

- Projected credits: 482.
- Actual credits consumed: 482.
- Full bulk request count: 1.

The raw response is stored under run `20261118T030326747840Z`. Loading and
idempotency tests replay this file and make no API calls.

## Developed components

| Component | Purpose |
|---|---|
| `config/graded_price_ingestion.json` | Declares scope, unverified-data label, USD, coverage games, safety buffer, and `include=ebay`. |
| `sql/008_create_graded_price_summaries.sql` | Creates the canonical latest/last-known graded summary model. |
| `src/gmad/graded_price_ingest.py` | Implements public coverage, credit projection, quota gating, one-time fetch, raw replay, validation, hashing, and guarded loading. |
| `scripts/sync_graded_prices.py` | Exposes mutually exclusive `--fetch` and `--replay-run` workflows. |
| `sql/verify_graded_price_load.sql` | Verifies coverage, labels, windows, medians, last sales, integrity, and prior datasets. |
| `sql/test_graded_price_constraints.sql` | Rollback-only validation of nullable medians, historical last sales, last-known state, and invalid values. |
| `POST_MVP_IMPROVEMENTS.md` | Records grade normalization and other noncritical refinements. |

## Data semantics

The canonical key is:

```text
card_id + source_name + currency_code + printing + grade_label
```

Important fields are intentionally separate:

- `median_30d`: nullable current 30-day graded median.
- `sales_30d`: provider-reported sales in that window.
- `last_sale_price` and `last_sold_date`: most recent historical reported sale,
  which can predate the current window.
- `graded_days`: graded rolling-window completeness.
- `ungraded_days`: retained separately and never used as graded coverage.
- `provider_as_of`: provider summary date.
- `coverage_checked_at`: source snapshot capture time.
- `is_reported_in_latest_snapshot`: distinguishes currently reported summaries
  from retained last-known observations.

Raw grade labels remain unparsed. An absent grade is never converted to zero or
deleted. When a newer source snapshot omits a previously stored grade, the row
is retained and marked last-known.

## Verified results

- 1,264 canonical graded-summary rows across 169 cards.
- Set coverage: Mega Brave 47 cards/479 rows, Mega Symphonia 44/451, Pitch Black
  48/249, and OP-17 English 30/85.
- 49 distinct raw grade labels.
- 514 rows with a non-null 30-day median.
- 750 rows with a NULL 30-day median and a preserved historical last sale.
- All 1,264 rows had `graded_days = 30`; `ungraded_days` was also 30 but remained
  a separate field.
- Zero orphan rows, duplicate canonical keys, negative values, future last-sale
  dates, or invalid window lengths.
- Earlier datasets remained unchanged: 489 current prices, 1,219 condition
  prices, and 117,828 historical prices.

The saved raw JSON was replayed twice. The first replay inserted 1,264 rows; the
second inserted or updated none and classified all 1,264 as unchanged. A direct
older-source test left both the stored hash and current/last-known flag intact.

## Presentation warning

Every Task 8 metric should be displayed as a provider-reported, unverified eBay
aggregate. A complete 30-day window does not guarantee adequate sample size,
correct grade matching, or a reliable valuation. Historical last sales must not
be displayed as current 30-day medians when `median_30d` is NULL.

