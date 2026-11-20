# Chapter 9 — SQL Verification and Testing

## Four kinds of assurance

- **Constraints** reject invalid writes continuously.
- **Data-quality queries** describe the rows currently stored.
- **Rollback-only integration tests** attempt valid and invalid writes against
  the real schema, then undo them.
- **Pipeline replay tests** run Python loading logic against saved evidence to
  verify idempotency and conflict behavior.

The repository does not contain a separate Python unit-test suite; do not claim
that rollback SQL or replay tests are unit tests.

## Practical verification queries

### Counts and set coverage

Adapted from `sql/verify_price_history_load.sql`:

```sql
SELECT s.set_name,
       count(DISTINCT c.card_id) AS catalog_cards,
       count(DISTINCT ph.card_id) AS cards_with_history,
       count(ph.price_history_id) AS history_rows
FROM sets s
JOIN cards c ON c.set_id = s.set_id
LEFT JOIN price_history ph ON ph.card_id = c.card_id
GROUP BY s.set_id, s.set_name;
```

The LEFT JOIN keeps cards with no history visible.

### Orphans

```sql
SELECT count(*) AS orphan_rows
FROM current_prices f
LEFT JOIN cards d ON d.card_id = f.card_id
WHERE d.card_id IS NULL;
```

The expected result is zero; the foreign key also prevents new orphans.

### Duplicate canonical keys

```sql
SELECT card_id, source_name, currency_code, printing, count(*)
FROM current_prices
GROUP BY card_id, source_name, currency_code, printing
HAVING count(*) > 1;
```

No returned rows means no duplicate groups.

### NULL, zero, and invalid prices

```sql
SELECT count(*) FILTER (WHERE market_price IS NULL) AS nulls,
       count(*) FILTER (WHERE market_price = 0) AS zeroes,
       count(*) FILTER (WHERE market_price < 0) AS negatives
FROM current_prices;
```

Never combine `IS NULL` and `= 0` into one quality category.

### Timestamp ordering

```sql
SELECT count(*)
FROM current_prices
WHERE no_market_price_since > provider_observed_at;
```

The check constraint and verification should both report no violations.

### Snapshot consistency

`sql/verify_reporting_views.sql` proves that the sale reporting view contains
one snapshot key and that its count equals the pinned operational subset. It
also checks all currency values remain null and all verification labels match.

### Previous datasets unchanged

Later verification scripts return counts from earlier tables. Task 9 confirmed
489 cards, 489 current rows, 1,219 condition rows, 1,264 graded rows, and 117,828
history rows after loading sales. This catches unintended side effects.

## Rollback-only tests

`sql/test_core_constraints.sql` begins a transaction, inserts fixed high-value
synthetic identities with `OVERRIDING SYSTEM VALUE`, catches expected
`unique_violation`, `foreign_key_violation`, `check_violation`, and
`not_null_violation`, prints results, then executes `ROLLBACK`.

This is useful because it tests PostgreSQL itself without advancing real
identity sequences or retaining test rows. Task-specific files test zero/NULL
preservation, negative rejection, graded last-known transitions, and sale replay
uniqueness.

Run safely:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\verify_reported_sale_load.sql --read-only
.\.venv\Scripts\python.exe .\scripts\run_sql_file.py .\sql\test_reported_sale_constraints.sql
```

The runner labels `verify` as read-only and recognizes `test_` files, but the
SQL file itself is responsible for its final rollback.

## Idempotency proof

Replaying the same graded raw file twice produced 1,264 inserts then 1,264
unchanged. Replaying the completed sale snapshot produced 12,568 inserts then
12,568 unchanged. A deliberately changed hash on the same immutable sale replay
key raised `DataIntegrityError` before a write.

## Practice exercises

1. Write a query that groups `reported_sale_observations` by snapshot key and
   reports rows, distinct cards, null currencies, and minimum/maximum sold
   dates. Compare it with `sql/verify_reported_sale_load.sql`.
2. Write duplicate detection for the `condition_prices` canonical grain. Why
   should a correct result contain zero rows rather than one row containing
   zero?
3. Add a rollback-only test that attempts a negative current price and catches
   `check_violation`. Explain why the final `ROLLBACK` is still required.
4. Given first-replay counts `inserted=12568, unchanged=0` and second-replay
   counts `inserted=0, unchanged=12568`, state exactly what idempotency is
   proven—and what cross-snapshot identity is not proven.

Solutions are in [Exercise answer key](16_EXERCISE_ANSWER_KEY.md#chapter-9--sql-verification-and-testing).

