-- Task 8: latest provider-reported aggregated graded sold-price summaries.

BEGIN;

CREATE TABLE graded_price_summaries (
    graded_price_summary_id BIGINT GENERATED ALWAYS AS IDENTITY,
    card_id BIGINT NOT NULL,
    printing TEXT NOT NULL,
    grade_label TEXT NOT NULL,
    median_30d NUMERIC(30, 16),
    sales_30d INTEGER NOT NULL,
    last_sale_price NUMERIC(30, 16),
    last_sold_date DATE,
    ungraded_days INTEGER,
    graded_days INTEGER,
    provider_as_of DATE NOT NULL,
    is_reported_in_latest_snapshot BOOLEAN NOT NULL DEFAULT TRUE,
    coverage_checked_at TIMESTAMPTZ NOT NULL,
    source_name TEXT NOT NULL,
    currency_code CHAR(3) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_record_hash CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_graded_price_summaries
        PRIMARY KEY (graded_price_summary_id),
    CONSTRAINT fk_graded_price_summaries_card
        FOREIGN KEY (card_id)
        REFERENCES cards (card_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT uq_graded_price_summaries_canonical_snapshot
        UNIQUE (card_id, source_name, currency_code, printing, grade_label),
    CONSTRAINT chk_graded_price_summaries_id_positive
        CHECK (graded_price_summary_id > 0),
    CONSTRAINT chk_graded_price_summaries_card_id_positive
        CHECK (card_id > 0),
    CONSTRAINT chk_graded_price_summaries_printing_not_blank
        CHECK (btrim(printing) <> ''),
    CONSTRAINT chk_graded_price_summaries_grade_not_blank
        CHECK (btrim(grade_label) <> ''),
    CONSTRAINT chk_graded_price_summaries_median_nonnegative
        CHECK (median_30d IS NULL OR median_30d >= 0),
    CONSTRAINT chk_graded_price_summaries_sales_nonnegative
        CHECK (sales_30d >= 0),
    CONSTRAINT chk_graded_price_summaries_last_price_nonnegative
        CHECK (last_sale_price IS NULL OR last_sale_price >= 0),
    CONSTRAINT chk_graded_price_summaries_ungraded_days
        CHECK (ungraded_days IS NULL OR ungraded_days BETWEEN 0 AND 30),
    CONSTRAINT chk_graded_price_summaries_graded_days
        CHECK (graded_days IS NULL OR graded_days BETWEEN 0 AND 30),
    CONSTRAINT chk_graded_price_summaries_source_name_not_blank
        CHECK (btrim(source_name) <> ''),
    CONSTRAINT chk_graded_price_summaries_currency_code
        CHECK (currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT chk_graded_price_summaries_source_file_not_blank
        CHECK (btrim(source_file) <> ''),
    CONSTRAINT chk_graded_price_summaries_source_row_positive
        CHECK (source_row_number > 0),
    CONSTRAINT chk_graded_price_summaries_source_hash_sha256
        CHECK (source_record_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_graded_price_summaries_card_id
    ON graded_price_summaries (card_id);

CREATE INDEX idx_graded_price_summaries_provider_as_of
    ON graded_price_summaries (provider_as_of);

CREATE INDEX idx_graded_price_summaries_currently_reported
    ON graded_price_summaries (is_reported_in_latest_snapshot);

COMMENT ON TABLE graded_price_summaries IS
    'Latest provider-reported aggregated eBay graded sold-price summaries; unverified and potentially incomplete.';

COMMENT ON COLUMN graded_price_summaries.grade_label IS
    'Raw provider grade label such as PSA 10 or BGS 10 Black; intentionally not parsed during Task 8.';

COMMENT ON COLUMN graded_price_summaries.median_30d IS
    'Nullable provider-reported rolling 30-day graded median, separate from the last reported sale.';

COMMENT ON COLUMN graded_price_summaries.last_sale_price IS
    'Most recent provider-reported historical sale price, which may exist when median_30d is null.';

COMMENT ON COLUMN graded_price_summaries.ungraded_days IS
    'Provider ungraded days coverage retained separately; never substituted for graded_days.';

COMMENT ON COLUMN graded_price_summaries.graded_days IS
    'Provider graded rolling-window coverage; 30 indicates a complete 30-day window.';

COMMENT ON COLUMN graded_price_summaries.is_reported_in_latest_snapshot IS
    'False identifies a retained last-known grade summary absent from the newest accepted source snapshot.';

COMMENT ON COLUMN graded_price_summaries.coverage_checked_at IS
    'Timestamp when the source snapshot last confirmed presence or absence of this canonical grade key.';

COMMIT;
