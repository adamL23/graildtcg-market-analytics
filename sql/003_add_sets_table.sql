-- Forward-only normalization of set metadata.
-- The applied schema is still empty, so no provider values need to be guessed.

DO $$
BEGIN
    IF to_regclass('public.sets') IS NOT NULL THEN
        RAISE EXCEPTION '003_add_sets_table has already been applied';
    END IF;

    IF EXISTS (SELECT 1 FROM cards)
       OR EXISTS (SELECT 1 FROM price_history) THEN
        RAISE EXCEPTION
            '003_add_sets_table requires empty cards and price_history tables; explicit data migration is required for populated tables';
    END IF;
END
$$;

CREATE TABLE sets (
    set_id BIGINT GENERATED ALWAYS AS IDENTITY,
    tcgapi_set_id BIGINT,
    source_set_key TEXT NOT NULL,
    game_id BIGINT NOT NULL,
    game_name TEXT NOT NULL,
    set_name TEXT NOT NULL,
    set_code TEXT,
    language_code TEXT NOT NULL,
    region_code TEXT,
    release_date DATE,
    source_name TEXT NOT NULL,
    source_observed_at TIMESTAMPTZ,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_sets PRIMARY KEY (set_id),
    CONSTRAINT uq_sets_source_set_key
        UNIQUE (source_name, source_set_key),
    CONSTRAINT uq_sets_source_tcgapi_set_id
        UNIQUE (source_name, tcgapi_set_id),
    CONSTRAINT chk_sets_id_positive
        CHECK (set_id > 0),
    CONSTRAINT chk_sets_tcgapi_set_id_positive
        CHECK (tcgapi_set_id IS NULL OR tcgapi_set_id > 0),
    CONSTRAINT chk_sets_source_set_key_not_blank
        CHECK (btrim(source_set_key) <> ''),
    CONSTRAINT chk_sets_game_id_positive
        CHECK (game_id > 0),
    CONSTRAINT chk_sets_game_name_not_blank
        CHECK (btrim(game_name) <> ''),
    CONSTRAINT chk_sets_name_not_blank
        CHECK (btrim(set_name) <> ''),
    CONSTRAINT chk_sets_code_not_blank
        CHECK (set_code IS NULL OR btrim(set_code) <> ''),
    CONSTRAINT chk_sets_language_code
        CHECK (language_code ~ '^[a-z]{2,3}(-[A-Z][a-z]{3})?$'),
    CONSTRAINT chk_sets_region_code_not_blank
        CHECK (region_code IS NULL OR btrim(region_code) <> ''),
    CONSTRAINT chk_sets_source_name_not_blank
        CHECK (btrim(source_name) <> '')
);

ALTER TABLE cards
    DROP CONSTRAINT chk_cards_game_id_positive,
    DROP CONSTRAINT chk_cards_set_id_positive,
    DROP COLUMN game_id,
    DROP COLUMN game_name,
    DROP COLUMN game_slug,
    DROP COLUMN set_id,
    DROP COLUMN set_name;

ALTER TABLE cards
    ADD COLUMN set_id BIGINT NOT NULL,
    ADD CONSTRAINT chk_cards_set_id_positive
        CHECK (set_id > 0),
    ADD CONSTRAINT fk_cards_set
        FOREIGN KEY (set_id)
        REFERENCES sets (set_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

CREATE INDEX idx_cards_set_id
    ON cards (set_id);

COMMENT ON TABLE sets IS
    'Canonical set/release identity and metadata shared by many cards.';

COMMENT ON COLUMN sets.tcgapi_set_id IS
    'Nullable TCGAPI.dev set ID. Unique within source_name when present.';

COMMENT ON COLUMN sets.source_set_key IS
    'Stable ETL-supplied identity in the source namespace. Required even when no provider set ID exists.';

COMMENT ON COLUMN sets.set_code IS
    'Optional official set code; maps to TCGAPI.dev abbreviation when that field is available.';

COMMENT ON COLUMN sets.language_code IS
    'Lowercase ISO language code with optional script subtag, such as en, ja or zh-Hans. Region is stored separately.';

COMMENT ON COLUMN sets.region_code IS
    'Optional normalized release/market region. Catalog references must be resolved outside the schema before insertion.';

COMMENT ON COLUMN cards.set_id IS
    'GraildTCG internal set identity; references sets.set_id, not a provider set ID.';

