# Task 9 — Individual Sales Discovery Gate

## Gate outcome

Representative `include=ebay_sales` discovery is complete. The full 481-card
extraction has **not** been performed, and migration `009` has **not** been
created.

The verified response does not contain a stable sale, listing, item, or
transaction ID. Task 9 should therefore use a **sale-observation model**, not an
event table that claims cross-snapshot uniqueness.

## Preserved discovery scope

The discovery run is `20261118T033626665427Z`. It contains:

- An eligibility snapshot of the 481 cards with non-null eBay data in Task 8 run
  `20261118T030326747840Z`.
- One exact `include=ebay_sales` response for a representative card from each
  loaded set.
- A second exact response for multi-printing Pitch Black card `2163448` to test
  stability across repeated calls.
- A manifest and structured analysis file.

Representatives were selected for high information content:

- Pitch Black `2163448`, with Holofoil and Reverse Holofoil rows.
- OP-17 English `2185478`, with Foil and Normal rows.
- Mega Brave `985682`, with substantial graded and ungraded activity.
- Mega Symphonia `983913`, with substantial graded and ungraded activity.

Five requests consumed 10 credits. The final response reported 9,496 daily
credits remaining.

## Actual response schema

Each price row retains its parent `printing` and `ebay` summary. The individual
`ebay.sales` entries contained exactly these fields:

| Field | Observed type and meaning |
|---|---|
| `sold_date` | ISO date string; no time-of-day or timezone |
| `price` | Non-null numeric sale price |
| `best_offer` | Non-null boolean |
| `list_price` | Numeric or null; populated for 8 of 314 observations |
| `grade` | Provider text or null; populated for 130 observations |
| `condition` | Provider text or null; populated for 121 observations |
| `title` | Non-null original listing title |
| `url` | Non-null eBay listing URL |

No individual record contained:

- A stable provider sale/listing/item/transaction ID field.
- A currency or currency-code field.
- A sale timestamp beyond the date-only `sold_date`.
- A provider observation timestamp.

The parent `ebay.as_of` value is a date, not a timestamp. Task 9 must preserve
that date and the local raw-capture timestamp separately. Currency must remain
unknown/null unless a future verified response supplies it; it must not be
inferred from the domain or account configuration.

## Identity reliability

The 314 representative observations had 314 unique URLs across cards and
printings. The repeated Pitch Black request returned the same 50 sale rows in
the same order with identical URL sets.

This demonstrates short-term response stability, but not event identity:

- A listing URL can represent multiple quantity sales.
- A seller can relist an equivalent item.
- The response does not state that one URL equals one completed transaction.
- The URL is not documented as a provider sale identifier.

Deterministic fingerprints excluding URL are demonstrably unsafe. Five groups,
containing seven extra rows, shared the same card, printing, sold date, price,
best-offer value, list price, grade, condition, and title while having different
URLs.

The URL should therefore be retained as source evidence but not declared a
unique sale key. A normalized fingerprint may support later comparison, but it
must not carry a uniqueness constraint.

## Coverage, window, and limits

The four representative responses contained six printing rows and 314 sales
observations. For every printing row:

```text
sales array length
= ungraded sales_30d
+ sum of graded sales_30d
```

The oldest observation was 29 days before its parent `as_of` date, and all
parent `days` and `graded_days` values were 30. The largest sales array contained
124 rows, demonstrating that the response is not capped at 100 observations.

However, the response exposed no pagination parameters, `has_more`, next-page
token, total-sales field, or explicit cap. Exact reconciliation in this sample
supports the interpretation that the array represents the provider's available
30-day aggregate components, but it does not prove universal completeness.
Omitted observations must never be interpreted as zero activity.

## Aggregate comparison

Representative reconciliation included:

- Pitch Black Holofoil: 17 array rows and 17 ungraded aggregate sales.
- Pitch Black Reverse Holofoil: 33 and 33.
- OP-17 Foil: 58 and 58; its Normal row reported zero and returned an empty
  array.
- Mega Brave Holofoil: 124 rows = 35 ungraded + 89 graded aggregate sales.
- Mega Symphonia Holofoil: 82 rows = 41 ungraded + 41 graded aggregate sales.

This is a validation signal, not an invariant that future ETL should require.

## Recommended MVP model

Use a table named `reported_sale_observations`, not `reported_sales` or a table
that implies verified unique transactions.

Each row should preserve one provider-returned observation within one captured
source snapshot. The replay-idempotency key should be:

```text
source_snapshot_key + card_id + printing + source_row_number
```

This key prevents duplicate loading of the same saved JSON but makes no claim
that observations in different snapshots represent different real-world sales.

Recommended fields, subject to approval before migration `009`:

- Internal observation ID and `card_id` foreign key.
- Source snapshot key and one-based source row number.
- Printing.
- Exact `sold_date`, `price`, `best_offer`, nullable `list_price`, raw `grade`,
  raw `condition`, exact `title`, and exact `url`.
- Nullable currency code, left null for the verified response.
- Parent `ebay.as_of`, `days`, and `graded_days`.
- Raw-capture timestamp and database ingestion timestamp.
- Source path and normalized observation hash.
- Non-unique analytical fingerprint for future comparison only.
- Explicit provider-reported/unverified label in documentation and reporting.

Observations from a later extraction should be appended under a new source
snapshot key. Cross-snapshot event deduplication is intentionally deferred until
a reliable provider identity or stronger evidence exists.

## Full-extraction plan and credit gate

The frozen eligibility snapshot contains 481 cards. At two credits per card, the
projected extraction cost is 962 credits. The most recent discovery response
reported 9,496 credits remaining.

Before full extraction, the implementation should require:

- A fresh quota probe.
- The 962-credit projection plus a configurable safety buffer to fit.
- Bounded concurrency of four workers.
- At most three attempts per card.
- Retries only for transient network, 429, and 5xx failures.
- Immediate raw-file persistence after every successful response.
- A resumable manifest that never repeats completed card IDs.
- Offline-only parsing, loading, fixes, and idempotency tests.

The eligibility list remains frozen to the Task 8 snapshot for this first run.
Coverage changes during extraction will be reported, not used to silently alter
scope.

## Decision required

Approve the observation model and extraction controls before proceeding with
migration `009` and the full 481-card request sequence.

