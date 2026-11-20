"""Snapshot, validate, and upsert cached TCGAPI.dev condition prices."""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from gmad.config import PROJECT_ROOT
from gmad.db import connect
from gmad.tcgapi_client import TcgApiClient


@dataclass(frozen=True)
class ConditionPriceConfig:
    source_name: str
    currency_code: str
    batch_size: int
    expected_card_count: int
    source_set_keys: tuple[str, ...]


@dataclass(frozen=True)
class CardIdentity:
    card_id: int
    tcgapi_card_id: int
    source_set_key: str
    set_name: str


@dataclass(frozen=True)
class ConditionPriceRow:
    card_id: int
    tcgapi_card_id: int
    printing: str
    condition_name: str
    listing_language: str
    low_price: Decimal | None
    lowest_with_shipping: Decimal | None
    median_with_shipping: Decimal | None
    sample_count: int
    provider_observed_at: datetime
    source_name: str
    currency_code: str
    source_file: str
    source_row_number: int
    source_record_hash: str

    @property
    def canonical_key(self) -> tuple[int, str, str, str, str, str]:
        return (
            self.card_id,
            self.source_name,
            self.currency_code,
            self.printing,
            self.condition_name,
            self.listing_language,
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


def _timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO timestamp.") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return timestamp


def _decimal_for_hash(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _record_hash(row: ConditionPriceRow) -> str:
    normalized = {
        "condition_name": row.condition_name,
        "currency_code": row.currency_code,
        "listing_language": row.listing_language,
        "low_price": _decimal_for_hash(row.low_price),
        "lowest_with_shipping": _decimal_for_hash(row.lowest_with_shipping),
        "median_with_shipping": _decimal_for_hash(row.median_with_shipping),
        "printing": row.printing,
        "provider_observed_at": row.provider_observed_at.isoformat(),
        "sample_count": row.sample_count,
        "source_name": row.source_name,
        "tcgapi_card_id": row.tcgapi_card_id,
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


def load_condition_price_config(path: Path) -> ConditionPriceConfig:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    source_name = _required_text(payload.get("source_name"), "source_name")
    currency_code = _required_text(payload.get("currency_code"), "currency_code")
    if len(currency_code) != 3 or not currency_code.isupper():
        raise ValueError("currency_code must be three uppercase letters.")
    batch_size = _positive_int(payload.get("batch_size"), "batch_size")
    if batch_size > 500:
        raise ValueError("Bulk condition batch_size cannot exceed 500.")
    if payload.get("warm_missing_cards") is not False:
        raise ValueError(
            "Task 7 requires warm_missing_cards=false; cache warming is out of scope."
        )
    expected_card_count = _positive_int(
        payload.get("expected_card_count"), "expected_card_count"
    )
    source_set_keys = payload.get("source_set_keys")
    if not isinstance(source_set_keys, list) or not source_set_keys:
        raise ValueError("source_set_keys must be a nonempty array.")

    return ConditionPriceConfig(
        source_name=source_name,
        currency_code=currency_code,
        batch_size=batch_size,
        expected_card_count=expected_card_count,
        source_set_keys=tuple(
            _required_text(item, "source_set_keys item") for item in source_set_keys
        ),
    )


def select_cards(config: ConditionPriceConfig) -> list[CardIdentity]:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.card_id,
                    c.tcgapi_card_id,
                    s.source_set_key,
                    s.set_name
                FROM cards AS c
                JOIN sets AS s ON s.set_id = c.set_id
                WHERE s.source_name = %s
                  AND s.source_set_key = ANY(%s)
                ORDER BY c.tcgapi_card_id;
                """,
                (config.source_name, list(config.source_set_keys)),
            )
            cards = [CardIdentity(*row) for row in cursor.fetchall()]

    if len(cards) != config.expected_card_count:
        raise ValueError(
            f"Expected {config.expected_card_count} configured cards, found {len(cards)}."
        )
    if len({card.source_set_key for card in cards}) != len(config.source_set_keys):
        raise ValueError("One or more configured sets have no catalog cards.")
    return cards


def fetch_condition_prices(
    client: TcgApiClient,
    config: ConditionPriceConfig,
    cards: list[CardIdentity],
    run_directory: Path,
) -> tuple[list[ConditionPriceRow], dict[str, Any]]:
    card_map = {card.tcgapi_card_id: card for card in cards}
    canonical_rows: dict[
        tuple[int, str, str, str, str, str], ConditionPriceRow
    ] = {}
    cards_with_rows: set[int] = set()
    batches: list[dict[str, Any]] = []

    for start in range(0, len(cards), config.batch_size):
        batch_number = start // config.batch_size + 1
        batch_cards = cards[start : start + config.batch_size]
        requested_ids = [card.tcgapi_card_id for card in batch_cards]
        requested_id_set = set(requested_ids)
        payload, raw_text = client.get_bulk_conditions(requested_ids)
        raw_path = run_directory / f"batch_{batch_number:03d}.json"
        _write_raw(raw_path, raw_text)

        data = payload.get("data")
        meta = payload.get("meta")
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise ValueError(f"Malformed condition-price batch {batch_number}.")
        if meta.get("total") != len(data):
            raise ValueError(
                f"Condition batch {batch_number} meta.total does not match its rows."
            )

        batch_returned_ids: set[int] = set()
        for source_row_number, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                raise ValueError("Every condition-price item must be an object.")
            tcgapi_card_id = _positive_int(item.get("card_id"), "card_id")
            identity = card_map.get(tcgapi_card_id)
            if identity is None or tcgapi_card_id not in requested_id_set:
                raise ValueError(
                    f"Batch {batch_number} returned unrequested card {tcgapi_card_id}."
                )
            batch_returned_ids.add(tcgapi_card_id)
            cards_with_rows.add(tcgapi_card_id)

            row_without_hash = ConditionPriceRow(
                card_id=identity.card_id,
                tcgapi_card_id=tcgapi_card_id,
                printing=_required_text(item.get("printing"), "printing"),
                condition_name=_required_text(item.get("condition"), "condition"),
                listing_language=_required_text(item.get("language"), "language"),
                low_price=_optional_decimal(item.get("low_price"), "low_price"),
                lowest_with_shipping=_optional_decimal(
                    item.get("lowest_with_shipping"), "lowest_with_shipping"
                ),
                median_with_shipping=_optional_decimal(
                    item.get("median_with_shipping"), "median_with_shipping"
                ),
                sample_count=_nonnegative_int(
                    item.get("sample_count"), "sample_count"
                ),
                provider_observed_at=_timestamp(
                    item.get("last_updated_at"), "last_updated_at"
                ),
                source_name=config.source_name,
                currency_code=config.currency_code,
                source_file=_relative(raw_path),
                source_row_number=source_row_number,
                source_record_hash="",
            )
            row = replace(
                row_without_hash,
                source_record_hash=_record_hash(row_without_hash),
            )
            if row.canonical_key in canonical_rows:
                raise ValueError(
                    "Provider returned a duplicate canonical condition key for "
                    f"card {tcgapi_card_id}, {row.printing}, "
                    f"{row.condition_name}, {row.listing_language}."
                )
            canonical_rows[row.canonical_key] = row

        missing_ids = sorted(requested_id_set - batch_returned_ids)
        batches.append(
            {
                "batch_number": batch_number,
                "requested_cards": len(requested_ids),
                "cards_with_rows": len(batch_returned_ids),
                "provider_rows": len(data),
                "provider_omitted_ids": missing_ids,
                "raw_file": _relative(raw_path),
            }
        )

    rows = list(canonical_rows.values())
    condition_counts = Counter(row.condition_name for row in rows)
    printing_counts = Counter(row.printing for row in rows)
    language_counts = Counter(row.listing_language for row in rows)
    coverage_by_set = []
    for set_name in sorted({card.set_name for card in cards}):
        set_cards = {card.tcgapi_card_id for card in cards if card.set_name == set_name}
        coverage_by_set.append(
            {
                "set_name": set_name,
                "requested_cards": len(set_cards),
                "cards_with_rows": len(set_cards & cards_with_rows),
                "condition_rows": sum(
                    row.tcgapi_card_id in set_cards for row in rows
                ),
            }
        )

    return rows, {
        "cards_requested": len(cards),
        "cards_with_condition_rows": len(cards_with_rows),
        "cards_without_condition_rows": len(cards) - len(cards_with_rows),
        "provider_omitted_ids": sorted(set(card_map) - cards_with_rows),
        "canonical_rows_received": len(rows),
        "condition_counts": dict(sorted(condition_counts.items())),
        "printing_counts": dict(sorted(printing_counts.items())),
        "language_counts": dict(sorted(language_counts.items())),
        "median_null_with_sample_count_at_least_3": sum(
            row.median_with_shipping is None and row.sample_count >= 3 for row in rows
        ),
        "median_present_with_sample_count_below_3": sum(
            row.median_with_shipping is not None and row.sample_count < 3 for row in rows
        ),
        "provider_observed_at_min": (
            min(row.provider_observed_at for row in rows).isoformat()
            if rows
            else None
        ),
        "provider_observed_at_max": (
            max(row.provider_observed_at for row in rows).isoformat()
            if rows
            else None
        ),
        "coverage_by_set": coverage_by_set,
        "batches": batches,
    }


def load_condition_prices(
    config: ConditionPriceConfig,
    rows: list[ConditionPriceRow],
    selected_cards: list[CardIdentity],
) -> dict[str, Any]:
    selected_card_ids = [card.card_id for card in selected_cards]
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
                    condition_name,
                    listing_language,
                    provider_observed_at,
                    source_record_hash
                FROM condition_prices
                WHERE card_id = ANY(%s)
                  AND source_name = %s
                  AND currency_code = %s;
                """,
                (selected_card_ids, config.source_name, config.currency_code),
            )
            existing = {
                (
                    card_id,
                    source_name,
                    currency_code,
                    printing,
                    condition_name,
                    listing_language,
                ): (provider_observed_at, source_record_hash)
                for (
                    card_id,
                    source_name,
                    currency_code,
                    printing,
                    condition_name,
                    listing_language,
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
                                "condition_name": row.condition_name,
                                "listing_language": row.listing_language,
                                "change_type": "same_timestamp_revision",
                                "previous_hash": previous_hash,
                                "new_hash": row.source_record_hash,
                            }
                        )
                else:
                    updated_newer += 1

            cursor.execute(
                """
                CREATE TEMP TABLE incoming_condition_prices ON COMMIT DROP AS
                SELECT
                    card_id,
                    printing,
                    condition_name,
                    listing_language,
                    low_price,
                    lowest_with_shipping,
                    median_with_shipping,
                    sample_count,
                    provider_observed_at,
                    source_name,
                    currency_code,
                    source_file,
                    source_row_number,
                    source_record_hash
                FROM condition_prices
                WITH NO DATA;
                """
            )
            with cursor.copy(
                """
                COPY incoming_condition_prices (
                    card_id, printing, condition_name, listing_language,
                    low_price, lowest_with_shipping, median_with_shipping,
                    sample_count, provider_observed_at, source_name,
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
                            row.condition_name,
                            row.listing_language,
                            row.low_price,
                            row.lowest_with_shipping,
                            row.median_with_shipping,
                            row.sample_count,
                            row.provider_observed_at,
                            row.source_name,
                            row.currency_code,
                            row.source_file,
                            row.source_row_number,
                            row.source_record_hash,
                        )
                    )

            cursor.execute(
                """
                INSERT INTO condition_prices (
                    card_id, printing, condition_name, listing_language,
                    low_price, lowest_with_shipping, median_with_shipping,
                    sample_count, provider_observed_at, source_name,
                    currency_code, source_file, source_row_number,
                    source_record_hash
                )
                SELECT
                    card_id, printing, condition_name, listing_language,
                    low_price, lowest_with_shipping, median_with_shipping,
                    sample_count, provider_observed_at, source_name,
                    currency_code, source_file, source_row_number,
                    source_record_hash
                FROM incoming_condition_prices
                ON CONFLICT ON CONSTRAINT uq_condition_prices_canonical_snapshot
                DO UPDATE SET
                    low_price = EXCLUDED.low_price,
                    lowest_with_shipping = EXCLUDED.lowest_with_shipping,
                    median_with_shipping = EXCLUDED.median_with_shipping,
                    sample_count = EXCLUDED.sample_count,
                    provider_observed_at = EXCLUDED.provider_observed_at,
                    source_file = EXCLUDED.source_file,
                    source_row_number = EXCLUDED.source_row_number,
                    source_record_hash = EXCLUDED.source_record_hash,
                    loaded_at = CURRENT_TIMESTAMP
                WHERE
                    EXCLUDED.provider_observed_at
                        > condition_prices.provider_observed_at
                    OR (
                        EXCLUDED.provider_observed_at
                            = condition_prices.provider_observed_at
                        AND condition_prices.source_record_hash IS DISTINCT FROM
                            EXCLUDED.source_record_hash
                    );
                """
            )

            cursor.execute(
                """
                SELECT count(*)
                FROM condition_prices
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


def write_condition_price_manifest(
    path: Path,
    run_id: str,
    config: ConditionPriceConfig,
    fetch_result: dict[str, Any],
    load_result: dict[str, Any],
) -> None:
    manifest = {
        "run_id": run_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source_name": config.source_name,
        "currency_code": config.currency_code,
        "warm_missing_cards": False,
        **fetch_result,
        **load_result,
    }
    _write_json(path, manifest)
