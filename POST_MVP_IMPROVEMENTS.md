# Post-MVP Improvements Backlog

Noncritical refinements are recorded here so Phase 1 remains focused and
incremental.

## Graded pricing

- Normalize raw grade labels into grader, numeric grade, qualifier, and special
  designation only after reviewing the full provider label population.
- Add historical graded-summary snapshots if trend analysis needs more than the
  latest/last-known model.
- Add confidence and minimum-sales presentation rules for low-volume medians.
- Track graded coverage changes by provider snapshot over time.
- Consider separating currency-normalized analytical values from exact provider
  decimals in the reporting layer.
- Evaluate provider matching quality and outlier detection before using graded
  summaries in valuation decisions.

## Data pipeline and reporting

- Add structured pipeline-run tables, retry telemetry, alerts, and freshness
  service-level indicators during the dedicated observability phase.
- Add reporting-layer rounding and display conventions without changing exact
  stored source values.
- Add a controlled refresh/watchlist policy for cache-limited endpoints.
- Add a managed Power BI gateway, service workspace, deployment pipeline, and
  scheduled refresh only after the local model and dashboard measures stabilize.
- Add automated semantic-model tests for relationship direction, expected row
  counts, default summarization, and completed-snapshot selection.
- Consider field parameters, calculation groups, and a reusable currency-aware
  measure layer after the MVP visuals establish the required analytical paths.
- Add a reviewed snapshot-advance procedure and completion registry before more
  than one Task 9 extraction snapshot is eligible for reporting.

## Reported sales identity and quality

- Reassess sale-level identity if the provider adds a documented stable sale or
  transaction ID.
- Investigate whether eBay item URLs represent single sales, multi-quantity
  listing sales, or relisted inventory before using item numbers as identity.
- Develop explicitly non-authoritative cross-snapshot linkage heuristics without
  enforcing them as uniqueness constraints.
- Track whether the provider later documents sales-array pagination, caps,
  sampling, or total-count semantics.
- Add currency metadata only when supplied or authoritatively documented by the
  provider; do not infer it from URL domains.
- Consider transaction-quality scoring, outlier detection, and product/grade
  match review only after the MVP data foundation is complete.
- If multiple observation snapshots are collected later, add a reporting view
  that requires an explicit completed snapshot key and prevents accidental
  cross-snapshot summation.
- Evaluate durable pipeline-run storage outside OneDrive if extraction manifests
  become larger or refreshes become scheduled; the MVP retry-and-recovery logic
  is sufficient for the completed Task 9 run.
