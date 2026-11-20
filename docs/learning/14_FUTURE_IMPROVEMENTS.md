# Chapter 14 — Further Improvements and Learning Paths

Everything in this chapter is planned or exploratory. It is not completed Phase
1 functionality.

## Improvements already recorded in the backlog

### Observability

Add structured pipeline-run tables, attempt/retry telemetry, freshness service
levels, alerts, and dashboards. This becomes important when humans no longer
watch every local run. A good next exercise is to model `pipeline_runs` and
`pipeline_run_steps` without changing fact grains.

### Automated regression testing

The project has database constraints, SQL integration tests, verification
queries, and replay tests, but no automated CI test suite. Future work could run
fixture-based Python tests, migration tests in a temporary PostgreSQL database,
and semantic-model checks for relationships, counts, and summarization.

### Snapshot management

Before multiple Task 9 snapshots are promoted, add a completed-snapshot registry
and reviewed promotion process. Reporting should require one explicit snapshot
or a carefully designed comparison model; it must not blindly union observations
as new transactions.

### Grade normalization and confidence

Normalize raw labels into grader, numeric grade, qualifier, and designation only
after reviewing the full label population. Add low-volume confidence rules and
provider-match/outlier analysis before treating graded summaries as valuations.

### Orchestration and deployment

A production scheduler would need dependency ordering, run locks, secret
management, retries, backfills, quota gates, alerts, and rollback/recovery.
Containerization can make runtime dependencies reproducible; cloud object
storage can replace OneDrive for raw evidence; managed PostgreSQL can add backup
and availability features.

### Power BI productionization

Gateway, Service workspace, deployment pipelines, scheduled/incremental refresh,
calculation groups, field parameters, and currency-aware DAX are deferred until
the local model and required visuals stabilize. Incremental refresh is most
useful for large append-only history, not tiny dimensions.

### Scalable processing

Psycopg `COPY` is appropriate for 117,828 history rows and the current local
scope. Distributed processing is unnecessary overhead today. Consider larger
engines only when volume, latency, or multi-provider transformation exceeds what
well-indexed PostgreSQL and bounded Python batches can handle.

### Data-quality frameworks

Tools such as dbt tests, Great Expectations, or Soda can standardize checks, but
they should encode already-understood grains and semantics. A framework cannot
decide whether an observation is a transaction or whether missing means zero.

## Suggested learning path

1. Add fixture-based tests for one parser and one timestamp guard.
2. Build a temporary-database migration test.
3. Design a `pipeline_runs` observability schema.
4. Create explicit DAX measures for latest price and coverage.
5. Prototype a snapshot registry and promotion transaction.
6. Only then evaluate orchestration, containers, and cloud deployment.

## Final comprehension check

Choose one improvement and answer: What current pain triggers it? What new
failure modes does it introduce? Which Phase 1 invariants—grain, provenance,
NULL semantics, idempotency, least privilege—must it preserve?

