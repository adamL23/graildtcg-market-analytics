-- Forward-only revision of the already-applied Phase 1 schema.
-- This migration is intentionally safe only while the two tables are empty.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM cards)
       OR EXISTS (SELECT 1 FROM price_history) THEN
        RAISE EXCEPTION
            '002_revise_core_schema requires empty cards and price_history tables; explicit backfill is required for populated tables';
    END IF;
END
$$;

ALTER TABLE cards
    ADD COLUMN source_name TEXT NOT NULL,
    ALTER COLUMN source_file DROP NOT NULL,
    DROP CONSTRAINT chk_cards_source_file_not_blank,
    ADD CONSTRAINT chk_cards_id_positive
        CHECK (card_id > 0),
    ADD CONSTRAINT chk_cards_tcgplayer_id_positive
        CHECK (tcgplayer_id IS NULL OR tcgplayer_id > 0),
    ADD CONSTRAINT chk_cards_source_name_not_blank
        CHECK (btrim(source_name) <> ''),
    ADD CONSTRAINT chk_cards_source_file_not_blank
        CHECK (source_file IS NULL OR btrim(source_file) <> ''),
    ADD CONSTRAINT chk_cards_variant_name_not_blank
        CHECK (variant_name IS NULL OR btrim(variant_name) <> '');

ALTER TABLE price_history
    ADD COLUMN source_name TEXT NOT NULL,
    ADD COLUMN currency_code CHAR(3) NOT NULL,
    ALTER COLUMN source_file DROP NOT NULL,
    ALTER COLUMN source_row_number DROP NOT NULL,
    DROP CONSTRAINT uq_price_history_card_source_hash,
    DROP CONSTRAINT chk_price_history_source_file_not_blank,
    DROP CONSTRAINT chk_price_history_source_row_number_positive,
    ADD CONSTRAINT chk_price_history_id_positive
        CHECK (price_history_id > 0),
    ADD CONSTRAINT chk_price_history_source_name_not_blank
        CHECK (btrim(source_name) <> ''),
    ADD CONSTRAINT chk_price_history_currency_code
        CHECK (currency_code ~ '^[A-Z]{3}$'),
    ADD CONSTRAINT chk_price_history_source_file_not_blank
        CHECK (source_file IS NULL OR btrim(source_file) <> ''),
    ADD CONSTRAINT chk_price_history_source_row_number_positive
        CHECK (source_row_number IS NULL OR source_row_number > 0),
    ADD CONSTRAINT uq_price_history_canonical_observation
        UNIQUE (
            card_id,
            source_name,
            printing,
            currency_code,
            observation_date
        );

COMMENT ON COLUMN cards.source_name IS
    'Normalized provider identifier supplied by the ETL; not a TCGAPI response field.';

COMMENT ON COLUMN cards.variant_name IS
    'Optional normalized identity variant such as Parallel or Alternate Art; distinct from price printing and not a direct TCGAPI field.';

COMMENT ON COLUMN cards.source_file IS
    'Optional raw snapshot path. Null when the ingestion source is not persisted as a file.';

COMMENT ON TABLE price_history IS
    'Canonical daily ungraded price observations by card, provider, printing and currency.';

COMMENT ON COLUMN price_history.source_name IS
    'Normalized pricing-provider identifier supplied by the ETL; not a TCGAPI response field.';

COMMENT ON COLUMN price_history.currency_code IS
    'Explicit three-letter uppercase currency code supplied from verified provider/endpoint metadata.';

COMMENT ON COLUMN price_history.printing IS
    'Provider price category such as Normal, Foil or Holofoil; not the card identity variant.';

COMMENT ON COLUMN price_history.source_record_hash IS
    'SHA-256 of the normalized current observation. A changed hash on the canonical key signals a provider revision.';

COMMENT ON COLUMN price_history.source_file IS
    'Optional raw snapshot path. Null for direct API ingestion without a persisted snapshot.';

COMMENT ON COLUMN price_history.source_row_number IS
    'Optional one-based row position for file-oriented ingestion; null for direct API observations.';

