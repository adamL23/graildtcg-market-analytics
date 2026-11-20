"""Snapshot, validate, and upsert latest TCGAPI.dev current prices."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from gmad.config import PROJECT_ROOT
from gmad.db import connect
from gmad.tcgapi_client import TcgApiClient


@dataclass(frozen=True)
class CurrentPriceConfig:
    source_name: str
    currency_code: str
    per_page: int
    expected_card_count: int
    source_set_keys: tuple[str, ...]


@dataclass(frozen=True)
class CardIdentity:
    card_id: int
    tcgapi_card_id: int


@dataclass(frozen=True)
class SetCatalog:
    set_id: int
    tcgapi_set_id: int
    source_set_key: str
    set_name: str
    cards: tuple[CardIdentity, ...]


@dataclass(frozen=True)
class CurrentPriceRow:
    card_id: int
    tcgapi_card_id: int
    printing: str
    market_price: Decimal | None
    low_price: Decimal | None
    median_price: Decimal | None
    lowest_with_shipping: Decimal | None
    total_listings: int
    market_price_as_of: date | None
    provider_observed_at: datetime
    no_market_price_since: datetime | None
    source_name: str
    currency_code: str
    source_file: str
    source_row_number: int
    source_record_hash: str

    @property
    def canonical_key(self) -> tuple[int, str, str, str]:
        return (
            self.card_id,
            self.source_name,
            self.currency_code,
            self.printing,
        )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string.")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer.")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer.")
    return value


def _optional_decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric or null.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} must be numeric or null.") from error
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be finite and nonnegative.")

    scale = max(0, -number.as_tuple().exponent)
    integer_digits = max(0, len(number.as_tuple().digits) + number.as_tuple().exponent)
    if scale > 16 or integer_digits > 14:
        raise ValueError(
            f"{field} cannot fit NUMERIC(30,16) without precision loss: {number}"
        )
    return number


def _optional_date(value: Any, field: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date string or null.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO date.") from error


def _timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO timestamp.") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return timestamp


def _optional_timestamp(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    return _timestamp(value, field)


def _decimal_for_hash(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _record_hash(row: CurrentPriceRow) -> str:
    normalized = {
        "currency_code": row.currency_code,
        "low_price": _decimal_for_hash(row.low_price),
        "lowest_with_shipping": _decimal_for_hash(row.lowest_with_shipping),
        "market_price": _decimal_for_hash(row.market_price),
        "market_price_as_of": (
            None if row.market_price_as_of is None else row.market_price_as_of.isoformat()
        ),
        "median_price": _decimal_for_hash(row.median_price),
        "no_market_price_since": (
            None
            if row.no_market_price_since is None
            else row.no_market_price_since.isoformat()
        ),
        "printing": row.printing,
        "provider_observed_at": row.provider_observed_at.isoformat(),
        "source_name": row.source_name,
        "tcgapi_card_id": row.tcgapi_card_id,
        "total_listings": row.total_listings,
    }
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _write_raw(path: Path, raw_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(raw_text)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def _relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def load_current_price_config(path: Path) -> CurrentPriceConfig:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    source_name = _required_text(payload.get("source_name"), "source_name")
    currency_code = _required_text(payload.get("currency_code"), "currency_code")
    if len(currency_code) != 3 or not currency_code.isupper():
        raise ValueError("currency_code must be three uppercase letters.")
    per_page = _positive_int(payload.get("per_page"), "per_page")
    if per_page > 200:
        raise ValueError("per_page cannot exceed the provider maximum of 200.")
    expected_card_count = _positive_int(
        payload.get("expected_card_count"), "expected_card_count"
    )
    source_set_keys = payload.get("source_set_keys")
    if not isinstance(source_set_keys, list) or not source_set_keys:
        raise ValueError("source_set_keys must be a nonempty array.")

    return CurrentPriceConfig(
        source_name=source_name,
        currency_code=currency_code,
        per_page=per_page,
        expected_card_count=expected_card_count,
        source_set_keys=tuple(
            _required_text(item, "source_set_keys item") for item in source_set_keys
        ),
    )


def select_catalog(config: CurrentPriceConfig) -> list[SetCatalog]:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    s.set_id,
                    s.tcgapi_set_id,
                    s.source_set_key,
                    s.set_name,
                    c.card_id,
                    c.tcgapi_card_id
                FROM sets AS s
                JOIN cards AS c ON c.set_id = s.set_id
                WHERE s.source_name = %s
                  AND s.source_set_key = ANY(%s)
                ORDER BY s.tcgapi_set_id, c.tcgapi_card_id;
                """,
                (config.source_name, list(config.source_set_keys)),
            )
            rows = cursor.fetchall()

    grouped: dict[int, dict[str, Any]] = {}
    for set_id, tcgapi_set_id, source_set_key, set_name, card_id, tcgapi_card_id in rows:
        if tcgapi_set_id is None:
            raise ValueError(f"Configured set {source_set_key} has no provider set ID.")
        item = grouped.setdefault(
            set_id,
            {
                "tcgapi_set_id": tcgapi_set_id,
                "source_set_key": source_set_key,
                "set_name": set_name,
                "cards": [],
            },
        )
        item["cards"].append(CardIdentity(card_id, tcgapi_card_id))

    catalogs = [
        SetCatalog(
            set_id=set_id,
            tcgapi_set_id=item["tcgapi_set_id"],
            source_set_key=item["source_set_key"],
            set_name=item["set_name"],
            cards=tuple(item["cards"]),
        )
        for set_id, item in grouped.items()
    ]
    if len(catalogs) != len(config.source_set_keys):
        raise ValueError(
            f"Expected {len(config.source_set_keys)} configured sets, found {len(catalogs)}."
        )
    card_count = sum(len(catalog.cards) for catalog in catalogs)
    if card_count != config.expected_card_count:
        raise ValueError(
            f"Expected {config.expected_card_count} configured cards, found {card_count}."
        )
    return sorted(catalogs, key=lambda catalog: catalog.tcgapi_set_id)


def fetch_current_prices(
    client: TcgApiClient,
    config: CurrentPriceConfig,
    catalogs: list[SetCatalog],
    run_directory: Path,
) -> tuple[list[CurrentPriceRow], dict[str, Any]]:
    all_cards = {
        card.tcgapi_card_id: card for catalog in catalogs for card in catalog.cards
    }
    rows: dict[tuple[int, str, str, str], CurrentPriceRow] = {}
    observed_card_ids: set[int] = set()
    page_results: list[dict[str, Any]] = []

    for catalog in catalogs:
        expected_ids = {card.tcgapi_card_id for card in catalog.cards}
        page = 1
        reported_total: int | None = None
        while True:
            payload, raw_text = client.get_json_with_raw(
                f"sets/{catalog.tcgapi_set_id}/cards",
                {"page": page, "per_page": config.per_page, "type": "Cards"},
            )
            raw_path = (
                run_directory
                / str(catalog.tcgapi_set_id)
                / f"cards_page_{page:03d}.json"
            )
            _write_raw(raw_path, raw_text)

            data = payload.get("data")
            meta = payload.get("meta")
            if not isinstance(data, list) or not isinstance(meta, dict):
                raise ValueError(
                    f"Malformed current-price page {page} for set "
                    f"{catalog.tcgapi_set_id}."
                )
            total = _positive_int(meta.get("total"), "meta.total")
            if reported_total is None:
                reported_total = total
            elif total != reported_total:
                raise ValueError(
                    f"Provider total changed during set {catalog.tcgapi_set_id}."
                )

            for source_row_number, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    raise ValueError("Every current-price response item must be an object.")
                tcgapi_card_id = _positive_int(item.get("id"), "card.id")
                if tcgapi_card_id not in expected_ids:
                    raise ValueError(
                        f"Set {catalog.tcgapi_set_id} returned unknown card "
                        f"{tcgapi_card_id}; run the catalog task before current prices."
                    )
                if tcgapi_card_id in observed_card_ids:
                    raise ValueError(f"Card {tcgapi_card_id} appeared more than once.")
                observed_card_ids.add(tcgapi_card_id)

                if _required_text(item.get("product_type"), "product_type") != "Cards":
                    raise ValueError(f"Card {tcgapi_card_id} is not product_type Cards.")
                provider_observed_at = _timestamp(
                    item.get("price_updated_at"), "price_updated_at"
                )
                no_market_price_since = _optional_timestamp(
                    item.get("no_market_price_since"), "no_market_price_since"
                )
                if (
                    no_market_price_since is not None
                    and no_market_price_since > provider_observed_at
                ):
                    raise ValueError(
                        f"Card {tcgapi_card_id} has no_market_price_since after "
                        "price_updated_at."
                    )

                identity = all_cards[tcgapi_card_id]
                row_without_hash = CurrentPriceRow(
                    card_id=identity.card_id,
                    tcgapi_card_id=tcgapi_card_id,
                    printing=_required_text(item.get("printing"), "printing"),
                    market_price=_optional_decimal(
                        item.get("market_price"), "market_price"
                    ),
                    low_price=_optional_decimal(item.get("low_price"), "low_price"),
                    median_price=_optional_decimal(
                        item.get("median_price"), "median_price"
                    ),
                    lowest_with_shipping=_optional_decimal(
                        item.get("lowest_with_shipping"), "lowest_with_shipping"
                    ),
                    total_listings=_nonnegative_int(
                        item.get("total_listings"), "total_listings"
                    ),
                    market_price_as_of=_optional_date(
                        item.get("market_price_as_of"), "market_price_as_of"
                    ),
                    provider_observed_at=provider_observed_at,
                    no_market_price_since=no_market_price_since,
                    source_name=config.source_name,
                    currency_code=config.currency_code,
                    source_file=_relative(raw_path),
                    source_row_number=source_row_number,
                    source_record_hash="",
                )
                row = CurrentPriceRow(
                    **{
                        **row_without_hash.__dict__,
                        "source_record_hash": _record_hash(row_without_hash),
                    }
                )
                if row.canonical_key in rows:
                    raise ValueError(
                        f"Duplicate canonical current-price key for card {tcgapi_card_id}."
                    )
                rows[row.canonical_key] = row

            page_results.append(
                {
                    "tcgapi_set_id": catalog.tcgapi_set_id,
                    "set_name": catalog.set_name,
                    "page": page,
                    "rows": len(data),
                    "raw_file": _relative(raw_path),
                }
            )
            if not meta.get("has_more"):
                break
            page += 1

        if reported_total != len(expected_ids):
            raise ValueError(
                f"Set {catalog.tcgapi_set_id} reported {reported_total} cards; "
                f"the database catalog has {len(expected_ids)}."
            )

    missing_ids = set(all_cards) - observed_card_ids
    if missing_ids:
        raise ValueError(
            "Current-price responses omitted configured cards: "
            + ", ".join(str(card_id) for card_id in sorted(missing_ids))
        )

    current_rows = list(rows.values())
    return current_rows, {
        "sets_requested": len(catalogs),
        "cards_requested": len(all_cards),
        "canonical_rows_received": len(current_rows),
        "market_price_nulls": sum(row.market_price is None for row in current_rows),
        "market_price_zeroes": sum(row.market_price == 0 for row in current_rows),
        "provider_observed_at_min": min(
            row.provider_observed_at for row in current_rows
        ).isoformat(),
        "provider_observed_at_max": max(
            row.provider_observed_at for row in current_rows
        ).isoformat(),
        "pages": page_results,
    }


def load_current_prices(
    config: CurrentPriceConfig,
    rows: list[CurrentPriceRow],
    catalogs: list[SetCatalog],
) -> dict[str, Any]:
    selected_card_ids = [card.card_id for catalog in catalogs for card in catalog.cards]
    incoming = {row.canonical_key: row for row in rows}

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    card_id,
                    source_name,
                    currency_code,
                    printing,
                    provider_observed_at,
                    source_record_hash
                FROM current_prices
                WHERE card_id = ANY(%s)
                  AND source_name = %s
                  AND currency_code = %s;
                """,
                (selected_card_ids, config.source_name, config.currency_code),
            )
            existing = {
                (card_id, source_name, currency_code, printing): (
                    provider_observed_at,
                    source_record_hash,
                )
                for (
                    card_id,
                    source_name,
                    currency_code,
                    printing,
                    provider_observed_at,
                    source_record_hash,
                ) in cursor.fetchall()
            }

            inserted = 0
            updated_newer = 0
            revised_same_timestamp = 0
            unchanged = 0
            older_skipped = 0
            changes: list[dict[str, Any]] = []
            for key, row in incoming.items():
                previous = existing.get(key)
                if previous is None:
                    inserted += 1
                    continue
                previous_observed_at, previous_hash = previous
                if row.provider_observed_at < previous_observed_at:
                    older_skipped += 1
                elif row.provider_observed_at == previous_observed_at:
                    if row.source_record_hash == previous_hash:
                        unchanged += 1
                    else:
                        revised_same_timestamp += 1
                        changes.append(
                            {
                                "tcgapi_card_id": row.tcgapi_card_id,
                                "printing": row.printing,
                                "change_type": "same_timestamp_revision",
                                "previous_hash": previous_hash,
                                "new_hash": row.source_record_hash,
                            }
                        )
                else:
                    updated_newer += 1

            cursor.execute(
                """
                CREATE TEMP TABLE incoming_current_prices ON COMMIT DROP AS
                SELECT
                    card_id,
                    printing,
                    market_price,
                    low_price,
                    median_price,
                    lowest_with_shipping,
                    total_listings,
                    market_price_as_of,
                    provider_observed_at,
                    no_market_price_since,
                    source_name,
                    currency_code,
                    source_file,
                    source_row_number,
                    source_record_hash
                FROM current_prices
                WITH NO DATA;
                """
            )
            with cursor.copy(
                """
                COPY incoming_current_prices (
                    card_id, printing, market_price, low_price, median_price,
                    lowest_with_shipping, total_listings, market_price_as_of,
                    provider_observed_at, no_market_price_since, source_name,
                    currency_code, source_file, source_row_number,
                    source_record_hash
                ) FROM STDIN
                """
            ) as copy:
                for row in rows:
                    copy.write_row(
                        (
                            row.card_id,
                            row.printing,
                            row.market_price,
                            row.low_price,
                            row.median_price,
                            row.lowest_with_shipping,
                            row.total_listings,
                            row.market_price_as_of,
                            row.provider_observed_at,
                            row.no_market_price_since,
                            row.source_name,
                            row.currency_code,
                            row.source_file,
                            row.source_row_number,
                            row.source_record_hash,
                        )
                    )

            cursor.execute(
                """
                INSERT INTO current_prices (
                    card_id, printing, market_price, low_price, median_price,
                    lowest_with_shipping, total_listings, market_price_as_of,
                    provider_observed_at, no_market_price_since, source_name,
                    currency_code, source_file, source_row_number,
                    source_record_hash
                )
                SELECT
                    card_id, printing, market_price, low_price, median_price,
                    lowest_with_shipping, total_listings, market_price_as_of,
                    provider_observed_at, no_market_price_since, source_name,
                    currency_code, source_file, source_row_number,
                    source_record_hash
                FROM incoming_current_prices
                ON CONFLICT ON CONSTRAINT uq_current_prices_canonical_snapshot
                DO UPDATE SET
                    market_price = EXCLUDED.market_price,
                    low_price = EXCLUDED.low_price,
                    median_price = EXCLUDED.median_price,
                    lowest_with_shipping = EXCLUDED.lowest_with_shipping,
                    total_listings = EXCLUDED.total_listings,
                    market_price_as_of = EXCLUDED.market_price_as_of,
                    provider_observed_at = EXCLUDED.provider_observed_at,
                    no_market_price_since = EXCLUDED.no_market_price_since,
                    source_file = EXCLUDED.source_file,
                    source_row_number = EXCLUDED.source_row_number,
                    source_record_hash = EXCLUDED.source_record_hash,
                    loaded_at = CURRENT_TIMESTAMP
                WHERE
                    EXCLUDED.provider_observed_at
                        > current_prices.provider_observed_at
                    OR (
                        EXCLUDED.provider_observed_at
                            = current_prices.provider_observed_at
                        AND current_prices.source_record_hash IS DISTINCT FROM
                            EXCLUDED.source_record_hash
                    );
                """
            )

            cursor.execute(
                """
                SELECT count(*)
                FROM current_prices
                WHERE card_id = ANY(%s)
                  AND source_name = %s
                  AND currency_code = %s;
                """,
                (selected_card_ids, config.source_name, config.currency_code),
            )
            database_rows = cursor.fetchone()[0]

    return {
        "inserted_rows": inserted,
        "updated_from_newer_snapshot": updated_newer,
        "revised_at_same_timestamp": revised_same_timestamp,
        "unchanged_rows": unchanged,
        "older_provider_rows_skipped": older_skipped,
        "existing_rows_not_returned": len(set(existing) - set(incoming)),
        "database_rows_after_load": database_rows,
        "change_details": changes,
    }


def write_current_price_manifest(
    path: Path,
    run_id: str,
    config: CurrentPriceConfig,
    fetch_result: dict[str, Any],
    load_result: dict[str, Any],
) -> None:
    manifest = {
        "run_id": run_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source_name": config.source_name,
        "currency_code": config.currency_code,
        **fetch_result,
        **load_result,
    }
    _write_json(path, manifest)
