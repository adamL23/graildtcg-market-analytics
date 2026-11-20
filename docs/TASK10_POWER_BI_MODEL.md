# Task 10 — Power BI Reporting Foundation

## Outcome

Task 10 is complete. PostgreSQL now exposes a six-view, read-only reporting
surface for Power BI, and the Power BI Desktop Import model is saved as
`GraildTCG Market Analytics Dashboard.pbix` in the project root.

The reporting layer does not modify or aggregate the operational datasets. It
preserves provider provenance, observation and ingestion timestamps, currency,
printing, raw grade labels, nullable values, and the Task 9 observation-quality
labels needed by later dashboard work.

## Reporting views and row grain

| Reporting view | Exact row grain | Verified rows |
| --- | --- | ---: |
| `reporting.dim_cards` | One row per canonical `public.cards.card_id` | 489 |
| `reporting.fact_current_prices` | One latest provider snapshot per card, source, currency, and printing | 489 |
| `reporting.fact_condition_prices` | One latest provider snapshot per card, source, currency, printing, condition, and listing language | 1,219 |
| `reporting.fact_graded_price_summaries` | One canonical summary per card, source, currency, printing, and raw grade label | 1,264 |
| `reporting.fact_price_history` | One canonical daily observation per card, source, printing, currency, and observation date | 117,828 |
| `reporting.fact_reported_sale_observations` | One provider-returned source-array observation per completed snapshot, card, printing, and source row number | 12,568 |

The view definitions and their PostgreSQL comments explicitly preserve these
grains. Verification confirmed that every reporting-view count equals its
underlying operational dataset count, except the reported-sales view, which is
intentionally restricted to one approved completed snapshot.

## Reported-sale snapshot policy

The reported-sales fact is pinned to:

`tcgapi.dev:ebay_sales:20261118T035224841879Z`

All 12,568 rows belong to this single snapshot. Every row retains the label
`Provider-reported, unverified observation`, and all 12,568 currency values
remain `NULL` because the provider did not supply currency. The view must not be
changed to combine extraction snapshots.

For a future completed extraction, update the literal snapshot key in
`sql/010_create_reporting_views.sql` through a new forward migration, verify the
new manifest is complete, rerun `sql/verify_reporting_views.sql`, and refresh
Power BI. Do not silently repoint the existing migration or union snapshots.

## Graded-price status semantics

`reporting.fact_graded_price_summaries` exposes both
`is_reported_in_latest_snapshot` and a display-safe `reporting_status`:

- `Current provider snapshot` means the grade is present in the latest accepted
  provider response.
- `Last-known observation` means the grade was retained from an older response
  and must not be presented as a current 30-day valuation.

The current database contains 1,264 current rows and no retained last-known rows.
The reporting model remains ready to distinguish them in a later refresh.
Nullable `median_30d` and historical `last_sale_price` remain separate fields.

## Read-only Power BI role

Power BI connects with the dedicated login `graildtcg_powerbi`. The role is:

- `LOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`, and
  `NOBYPASSRLS`;
- limited to five concurrent connections;
- granted `CONNECT` on `graildtcg`, `USAGE` on `reporting`, and `SELECT` only on
  the six reporting views; and
- denied direct `SELECT` access to the operational tables in `public`.

The generated local credential is stored only in ignored `.env.powerbi`.
`PGADMINPASSWORD` was removed from `.env` after setup. To recheck permissions:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\configure_power_bi_role.py --verify-only
```

## Power BI connection and model

Power BI Desktop uses the PostgreSQL connector in **Import** mode:

- Server: `localhost:5432`
- Database: `graildtcg`
- Authentication: Database
- Username: `graildtcg_powerbi`
- Password: the local value in `.env.powerbi`

Only the six `reporting` views are imported. The model contains five active,
single-direction relationships:

| One side | Many side | Cardinality | Filter direction |
| --- | --- | --- | --- |
| `dim_cards[card_id]` | `fact_current_prices[card_id]` | One-to-many | Cards to fact |
| `dim_cards[card_id]` | `fact_condition_prices[card_id]` | One-to-many | Cards to fact |
| `dim_cards[card_id]` | `fact_graded_price_summaries[card_id]` | One-to-many | Cards to fact |
| `dim_cards[card_id]` | `fact_price_history[card_id]` | One-to-many | Cards to fact |
| `dim_cards[card_id]` | `fact_reported_sale_observations[card_id]` | One-to-many | Cards to fact |

No fact-to-fact relationships remain. Although the current-price dataset has one
row per loaded card today, its relationship is deliberately modeled as
one-to-many so the semantic model follows the documented fact grain rather than
assuming a permanent one-to-one population.

Card filtering was validated structurally: all five relationships are active and
single-direction from the Cards dimension, and SQL verification found zero fact
rows without a matching card.

## Default summarization

Power BI default summarization is set to **Don't summarize** for all 14 raw price
columns:

- Current: `market_price`, `low_price`, `median_price`,
  `lowest_with_shipping`
- Condition: `low_price`, `lowest_with_shipping`, `median_with_shipping`
- Graded: `median_30d`, `last_sale_price`
- History: `market_price`, `low_price`, `avg_sales_price`
- Reported sales: `price`, `list_price`

Later measures must define intentional aggregation and currency/filter context.
Raw market observations and medians must not use implicit SUM.

## Verification results

`sql/verify_reporting_views.sql` passed with:

- all six expected row counts;
- all six grain-preservation checks true;
- one and only one reported-sales snapshot key;
- 12,568 nullable-currency sale observations and zero populated currency values;
- 1,264 current graded rows, zero last-known rows, and zero invalid status labels;
- zero orphan rows across all five facts; and
- unchanged operational counts: 489 cards, 117,828 history rows, 489 current
  prices, 1,219 condition prices, 1,264 graded summaries, and 12,568 reported
  sale observations.

The reporting login independently returned the same six view counts and was
unable to query `public.cards` or any other listed operational table.

Power BI Desktop completed a manual Refresh without a connection, credential,
query, or relationship error. The refreshed report was then saved successfully
to the project root. Power BI Service, gateway setup, scheduled refresh, and
dashboard visuals remain outside Task 10.

## Migration and support files

- `sql/010_create_reporting_views.sql` — fresh-database reporting migration
- `sql/010_fix_power_bi_view_names.sql` — one-time local forward rename after
  the initially applied view names collided with Power BI table names
- `sql/verify_reporting_views.sql` — read-only grain and semantic verification
- `scripts/configure_power_bi_role.py` — role setup and repeatable permission
  verification

