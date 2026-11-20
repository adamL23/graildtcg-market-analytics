-- TCGAPI.dev set catalogs can contain valid cards without a collector number
-- (for example, some DON!! cards). Preserve those rows as NULL.

ALTER TABLE cards
    DROP CONSTRAINT chk_cards_number_not_blank,
    ALTER COLUMN card_number DROP NOT NULL,
    ADD CONSTRAINT chk_cards_number_not_blank
        CHECK (card_number IS NULL OR btrim(card_number) <> '');

COMMENT ON COLUMN cards.card_number IS
    'Optional provider collector/card number. Null when the provider does not supply one.';

