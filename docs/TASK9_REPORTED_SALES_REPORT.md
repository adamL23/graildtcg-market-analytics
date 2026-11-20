# Task 9 — Provider-Reported Sale Observations

## Outcome

Task 9 is complete for the approved MVP scope. Migration `009` stores immutable
provider-returned observations without claiming that rows are globally unique
real-world transactions. The controlled extraction completed all 481 eligible
cards and the database contains 12,568 observations from one clearly identified
completed snapshot.

- Run: `20261118T035224841879Z`
- Snapshot key: `tcgapi.dev:ebay_sales:20261118T035224841879Z`
- Frozen eligibility source: Task 8 run `20261118T030326747840Z`
- Extraction status: complete
- Successful card responses: 481 of 481
- Terminal API failures: 0
- Missing sales arrays: 0
- Provider-reported card credits consumed: 962
- Daily quota remaining after completion: 8,532

The endpoint supplies observations but no stable sale, item, listing, or
transaction identifier. URLs are retained as source evidence but are not used as
unique event IDs. Dashboard queries must select this completed snapshot key and
must not sum multiple extraction snapshots as though repeated observations were
new sales.

## Components

| Component | Purpose |
|---|---|
| `config/reported_sale_ingestion.json` | Freezes the eligibility source and configures the quota buffer, 1,100-credit hard ceiling, four workers, and three-attempt limit. |
| `sql/009_create_reported_sale_observations.sql` | Creates the insert-only observation table and canonical replay-key constraint. |
| `src/gmad/reported_sale_ingest.py` | Implements quota gating, conservative attempt accounting, resumable extraction, raw persistence, deterministic parsing, immutable replay validation, and database loading. |
| `scripts/sync_reported_sales.py` | Exposes new fetch, same-run resume, and offline replay modes. |
| `sql/verify_reported_sale_load.sql` | Verifies snapshot counts, relationships, replay-key uniqueness, nullable currency, and unchanged prior datasets. |
| `sql/test_reported_sale_constraints.sql` | Runs rollback-only replay-key, price, and currency constraint checks. |

Every successful card response is stored under
`data/raw/tcgapi_sales/20261118T035224841879Z/cards`. The run manifest separates
provider failures, quota exhaustion, missing arrays, empty arrays, and local
persistence errors. The two load manifests record the first load and idempotent
second replay.

## Identity and replay model

The canonical replay key is:

```text
source_snapshot_key + card_id + printing + source_row_number
```

`source_row_number` is the one-based array position inside one card response's
specific printing row. The parser rejects repeated printing labels within a card
response because such a response would make that identity ambiguous.

The source snapshot key comes from the extraction manifest and is reused without
change during every offline replay. Rows are insert-only. Before loading, the ETL
compares every existing replay key and hash. A same-key/different-hash result
raises `DataIntegrityError`; no stored row is silently revised. An explicit
altered-hash test was rejected before any write.

The source record hash includes the replay identity, parent `ebay.as_of` date,
and the full normalized provider observation. Exact response text remains the
authoritative evidence in the saved raw file.

## Preserved fields and semantics

The table preserves the provider fields `sold_date`, `price`, `best_offer`,
`list_price`, `grade`, `condition`, `title`, and `url`. It also stores the parent
printing, parent `ebay.as_of` date, exact source file, response capture timestamp,
and record hash.

`currency_code` is NULL for all 12,568 observations. Neither the representative
nor full responses supplied a sale currency field, so Task 9 does not infer one
from TCGAPI.dev, eBay URLs, the account subscription, or other price datasets.
`provider_as_of` is a date on the parent printing summary, not a fabricated sale
timestamp.

These are provider-reported observations. They are not verified transactions,
and repeated extraction snapshots may contain the same underlying observations.

## Extraction safety and recovery

The baseline projection was 481 cards at two credits each, or 962 card credits.
The configuration also enforced:

- A 100-credit provider-quota safety buffer.
- A hard spend ceiling of 1,100 conservatively reserved credits.
- Four concurrent workers.
- At most three attempts per card.
- Retries only for network failures, HTTP 429, and HTTP 5xx responses.
- Immediate raw-body persistence before success is committed to the manifest.
- Same-run resume that skips every saved successful response.

The completed run reserved 974 credits pessimistically, including two quota
probes and five attempt reservations that failed locally before an HTTP request
was issued. Provider responses reported exactly 962 card credits. The two quota
probes were separately recorded, and the final provider counter was 8,532.

During the initial pass, OneDrive briefly locked the manifest destination six
times. This was a local manifest-persistence issue, not an API failure. The raw
body had already been saved for two affected cards, so resume recovered both
without another request. Five cards whose request had not started were then
requested. Atomic manifest replacement now retries short Windows/OneDrive locks.
The same run and snapshot key were retained throughout.

## Coverage

The 481 successful card responses contained 592 card-printing price rows:

- 12,568 individual observations.
- 341 cards with at least one observation.
- 404 card-printing groups with at least one observation.
- 188 present but empty sales arrays.
- 0 missing sales arrays.
- 0 price rows without an eBay object.
- 0 successful card responses without price rows.
- 0 provider currency fields.

An empty array means only that the provider returned no observations in that
array. It is not interpreted as proven zero marketplace activity.

| Loaded set | Language | Eligible cards | Cards with observations | Observations |
|---|---:|---:|---:|---:|
| ME05: Pitch Black | en | 119 | 119 | 8,684 |
| m1L: Mega Brave | ja | 92 | 44 | 1,376 |
| m1S: Mega Symphonia | ja | 92 | 50 | 1,054 |
| The World's Strongest Warriors | en | 178 | 128 | 1,454 |

The response still exposes no pagination, reported total, or completeness flag.
Task 9 therefore does not claim complete marketplace-sale coverage or reconcile
these observations as a full transaction ledger.

## Verification

The first offline replay inserted 12,568 rows. The second replay inserted zero
and classified all 12,568 rows as unchanged. Verification found:

- 0 duplicate replay-key groups.
- 0 orphan observation rows.
- 0 invalid rows.
- 12,568 NULL currencies and 0 populated currencies.
- 489 catalog cards unchanged.
- 489 current-price rows unchanged.
- 1,219 condition-price rows unchanged.
- 1,264 graded-summary rows unchanged.
- 117,828 historical-price rows unchanged.

Scraping, cross-snapshot transaction deduplication, seller analytics, marketplace
features, advanced reconciliation, and transaction-quality scoring remain out of
scope.
