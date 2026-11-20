# Chapter 8 — Data Quality and Reliability

Reliability is layered. Python validates external shapes; PostgreSQL enforces
invariants; manifests explain run completeness; verification SQL measures data;
raw files make the result auditable.

## Reliability controls

| Control | Implementation | Risk reduced |
| --- | --- | --- |
| Type/value validation | `_required_text`, `_positive_int`, Decimal/date parsers | malformed external JSON |
| Constraints | NOT NULL, CHECK, UNIQUE, FK | invalid or duplicate stored rows |
| Canonical keys | table-specific unique constraints | duplicate logical facts |
| Record hashes | normalized SHA-256 | unnoticed revisions |
| Provider-time guards | current/condition upsert WHERE clause | stale overwrite |
| Raw preservation | timestamped exact response files | loss of source evidence |
| Manifests | fetch/load counts, errors, coverage, credits | ambiguous run outcome |
| Offline replay | graded and sale CLIs | repeated paid requests |
| Resumability | per-card Task 9 state | restart duplication |
| Rollback tests | `BEGIN ... ROLLBACK` SQL | production contamination |

## NULL, zero, and missing

`NULL` means unknown/not supplied; zero is a supplied numeric value; missing can
mean absent from a response. GraildTCG preserves each separately. Current market
zeroes set a generated analytical flag but remain zero. Condition medians remain
`NULL` below the provider's sample threshold. Missing cache rows are retained as
last accepted snapshots, not overwritten with zeros.

## Real issue investigations

### Price precision

**Problem:** a history value had four decimals. **Root cause:** the original
`NUMERIC(12,2)` reflected an assumption, not the observed contract.
**Investigation:** pre-write validation found `0.1324`. **Solution:** migration
`005` widened all history prices to `NUMERIC(14,4)`; current/condition/graded
prices use `NUMERIC(30,16)` to preserve longer artifacts. **Lesson:** inspect
real payloads before finalizing financial scale; do not silently round.

### Bulk history omission

**Problem:** 489 cards were requested but only 488 had history. **Root cause:** a
valid no-history card was omitted from the successful bulk map.
**Investigation:** an individual request returned HTTP 200 with empty `data`.
**Solution:** classify and manifest provider omission separately from failure.
**Lesson:** transport success is not data completeness.

### Stale snapshots

**Problem:** reruns can contain older cached values. **Root cause:** provider
observation time and ingestion time are different clocks. **Investigation:**
altered older rows were replayed deliberately. **Solution:** Python classifies
them and SQL refuses an older update. **Lesson:** order snapshots by source time,
not by when your script happened to run.

### Graded median versus last sale

**Problem:** a grade can lack a current 30-day median yet have an older sale.
**Root cause:** rolling-window aggregates and historical last events measure
different things. **Solution:** separate nullable median, window sales, last
price/date, and `graded_days`. **Lesson:** do not coalesce unlike measures.

### Sale identity

**Problem:** individual rows had no stable sale ID. **Investigation:** repeated
requests were stable, but five identical transaction-field groups had different
URLs; a URL can represent relisting or quantity. **Solution:** model immutable
source observations keyed only for snapshot replay. **Lesson:** idempotency
identity is not necessarily real-world event identity.

### OneDrive locks

**Problem:** atomic manifest replacement was temporarily locked six times.
**Root cause:** local OneDrive/Windows file coordination, not API failure.
**Solution:** save raw bodies before marking success, retry atomic replacement,
and recover saved successes during same-run resume. **Lesson:** filesystem
reliability belongs in pipeline design.

## Coverage and completeness

The manifest distinguishes requested cards, cards returned, cards with any eBay
data, cards with graded summaries, empty arrays, missing arrays, request
failures, and quota exhaustion. These metrics must never be collapsed into one
“coverage” number. An omitted row is not automatically zero activity.

## Practice exercises

1. Design a test for a current-price input with the same canonical key, an
   older provider time, and a different hash. State the expected Python
   counter, SQL result, stored hash, and manifest entry.
2. A manifest reports 481 requested cards, 481 successful requests, 293 sales
   arrays with rows, 188 empty arrays, and zero missing arrays. State what is
   proven and what is not proven about marketplace activity.
3. Investigate a `median_30d=NULL`, `sales_30d=0`, `last_sale_price=80` row.
   Write one valid and two invalid analytical interpretations.
4. Two observations share price, date, title, grade, and condition but have
   different URLs. Explain why neither forced merging nor forced separation can
   establish real-world transaction identity from this evidence alone.

Solutions are in [Exercise answer key](16_EXERCISE_ANSWER_KEY.md#chapter-8--data-quality-and-reliability).

