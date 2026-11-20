# Second-Pass Change Summary

## Modified chapters

| File | Major improvement |
| --- | --- |
| `README.md` | Added the worked example, answer key, and review summary to the learning path. |
| `00_LEARNING_ROADMAP.md` | Linked the comprehension check to an expected answer. |
| `03_ENVIRONMENT_SETUP.md` | Linked the configuration failure exercise to its outcome. |
| `04_DATABASE_AND_SQL.md` | Added practical, line-by-line teaching for keys, constraints, NUMERIC, NULL/zero, INSERT/UPDATE, guarded upserts, transactions, rollback, temp tables, COPY, and indexes, including state transitions. |
| `05_API_AND_JSON.md` | Expanded parsing, validation, and error-classification exercises. |
| `06_PYTHON_CODEBASE_WALKTHROUGH.md` | Rebuilt the walkthrough around verified function signatures, parameters, return values, dependencies, data transformations, failure behavior, transactions, COPY, timestamp guards, replay, credits, and resume logic. |
| `07_ETL_PIPELINES.md` | Added canonical-grain, completeness, and partial-snapshot exercises. |
| `08_DATA_QUALITY_AND_RELIABILITY.md` | Added investigations for stale rows, coverage semantics, graded windows, and identity limits. |
| `09_SQL_VERIFICATION_AND_TESTING.md` | Added duplicate, rollback, snapshot, and idempotency exercises. |
| `10_POWER_BI_REPORTING.md` | Linked relationship testing to its expected result. |
| `11_CHALLENGES_AND_TRADEOFFS.md` | Linked the design-alternative exercise to a model answer. |
| `12_PIPELINE_OPERATIONS.md` | Added recovery, manifest-credit, and replay-order exercises. |
| `13_BUILD_YOUR_OWN_PIPELINE.md` | Replaced the earlier sketch with a complete beginner-reproducible project using immutable content-addressed raw files, exact commands, COPY, true no-op replay, newer/older tests, malformed-response handling, verification, and troubleshooting. |
| `15_END_TO_END_WORKED_EXAMPLE.md` | Added a real Bulbasaur current-price trace from saved TCGAPI JSON through Python, dataclass, hash, staging, canonical SQL, reporting views, and Power BI. |
| `16_EXERCISE_ANSWER_KEY.md` | Added expected outcomes and solutions in one separate chapter. |

## Validation performed

- Verified documented Python signatures against the current `src/gmad` source.
- Verified SQL examples against migrations 001–010 and the implemented loader
  statements.
- Queried the local database read-only to confirm the worked example's internal
  ID, canonical values, source path/row, reporting-view output, and exact hash.
- Executed the exact `schema.sql` and `load_fixture.py` code blocks extracted
  from Chapter 13 in a uniquely named temporary PostgreSQL schema. The schema
  was dropped in `finally`; operational GraildTCG tables were not modified.
- Confirmed: first insert affected one row; exact replay was unchanged and
  affected zero rows; newer data updated; older data was skipped; malformed
  data was preserved then rejected; four distinct fixtures produced four raw
  snapshots; final canonical price remained 13.00.
- Rechecked Markdown links, fenced blocks, Mermaid syntax structure, and literal
  repository references after editing.

## Remaining documentation gaps

- No live API requests were made, as required. The guide relies on preserved
  responses and manifests, so future provider-contract changes will require a
  later evidence-based review.
- The repository still has no standalone Python unit-test suite; existing
  assurance is SQL rollback testing, saved-evidence replay, and verification
  queries.
- Production orchestration, alerting, scheduled extraction, Power BI Service,
  gateway setup, and dashboard visuals remain outside the implemented Phase 1
  boundary.
- Reported sales still lack verified cross-snapshot transaction identity and
  explicit source currency; the guide intentionally does not resolve these by
  inference.
