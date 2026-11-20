"""Snapshot, validate, and upsert canonical TCGAPI.dev price history."""

from concurrent.futures import ThreadPoolExecutor
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
class HistoryConfig:
    source_name: str
    currency_code: str
    history_range: str
    batch_size: int
    max_workers: int
    expected_card_count: int
    source_set_keys: tuple[str, ...]


@dataclass(frozen=True)
class CardIdentity:
    card_id: int
    tcgapi_card_id: int
    source_set_key: str
    set_name: str


@dataclass(frozen=True)
class HistoryRow:
    card_id: int
    tcgapi_card_id: int
    observation_date: date
    printing: str
    market_price: Decimal | None
    low_price: Decimal | None
    avg_sales_price: Decimal | None
    sales_volume: int | None
    source_name: str
    currency_code: str
    source_file: str
    source_row_number: int
    source_record_hash: str

    @property
    def canonical_key(self) -> tuple[int, str, str, str, date]:
        return (
            self.card_id,
            self.source_name,
            self.printing,
            self.currency_code,
            self.observation_date,
        )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string.")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer.")
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
    if number.as_tuple().exponent < -4:
        raise ValueError(
            f"{field} has more than four decimal places and would lose precision: {number}"
        )
    return number


def _optional_nonnegative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer or null.")
    return value


def _decimal_for_hash(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _history_hash(
    tcgapi_card_id: int,
    observation_date: date,
    printing: str,
    market_price: Decimal | None,
    low_price: Decimal | None,
    avg_sales_price: Decimal | None,
    sales_volume: int | None,
    source_name: str,
    currency_code: str,
) -> str:
    normalized = {
        "avg_sales_price": _decimal_for_hash(avg_sales_price),
        "currency_code": currency_code,
        "date": observation_date.isoformat(),
        "low_price": _decimal_for_hash(low_price),
        "market_price": _decimal_for_hash(market_price),
        "printing": printing,
        "sales_volume": sales_volume,
        "source_name": source_name,
        "tcgapi_card_id": tcgapi_card_id,
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


def load_history_config(path: Path) -> HistoryConfig:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    source_name = _required_text(payload.get("source_name"), "source_name")
    currency_code = _required_text(
        payload.get("currency_code"), "currency_code"
    )
    if len(currency_code) != 3 or not currency_code.isupper():
        raise ValueError("currency_code must be three uppercase letters.")
    history_range = _required_text(
        payload.get("history_range"), "history_range"
    )
    if history_range not in {"month", "quarter", "year", "all"}:
        raise ValueError("Unsupported history_range.")
    batch_size = _positive_int(payload.get("batch_size"), "batch_size")
    if batch_size > 50:
        raise ValueError("Bulk history batch_size cannot exceed 50.")
    max_workers = _positive_int(payload.get("max_workers"), "max_workers")
    if max_workers > 8:
        raise ValueError("max_workers cannot exceed 8.")
    expected_card_count = _positive_int(
        payload.get("expected_card_count"), "expected_card_count"
    )
    source_set_keys = payload.get("source_set_keys")
    if not isinstance(source_set_keys, list) or not source_set_keys:
        raise ValueError("source_set_keys must be a nonempty array.")

    return HistoryConfig(
        source_name=source_name,
        currency_code=currency_code,
        history_range=history_range,
        batch_size=batch_size,
        max_workers=max_workers,
        expected_card_count=expected_card_count,
        source_set_keys=tuple(
            _required_text(item, "source_set_keys item")
            for item in source_set_keys
        ),
    )


def select_cards(config: HistoryConfig) -> list[CardIdentity]:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.card_id, c.tcgapi_card_id, s.source_set_key, s.set_name
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
    return cards


def fetch_history(
    client: TcgApiClient,
    config: HistoryConfig,
    cards: list[CardIdentity],
    run_directory: Path,
) -> tuple[list[HistoryRow], dict[str, Any]]:
    card_map = {card.tcgapi_card_id: card for card in cards}
    canonical_rows: dict[tuple[int, str, str, str, date], HistoryRow] = {}
    cards_with_history: set[int] = set()
    identical_duplicates = 0
    conflicting_duplicates: list[dict[str, Any]] = []
    provider_omitted_ids: list[int] = []
    batches: list[dict[str, Any]] = []

    batch_requests: list[tuple[int, list[int]]] = []
    for start in range(0, len(cards), config.batch_size):
        batch_number = start // config.batch_size + 1
        batch_cards = cards[start : start + config.batch_size]
        requested_ids = [card.tcgapi_card_id for card in batch_cards]
        batch_requests.append((batch_number, requested_ids))

    def request_batch(requested_ids: list[int]) -> tuple[dict[str, Any], str]:
        return client.get_bulk_history(requested_ids, config.history_range)

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        responses = list(
            executor.map(
                request_batch,
                [requested_ids for _, requested_ids in batch_requests],
            )
        )

    for (batch_number, requested_ids), (payload, raw_text) in zip(
        batch_requests, responses, strict=True
    ):
        raw_path = run_directory / f"batch_{batch_number:03d}.json"
        _write_raw(raw_path, raw_text)

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"Bulk history batch {batch_number} has no data object.")
        returned_ids: set[int] = set()
        batch_row_count = 0

        for key, observations in data.items():
            try:
                tcgapi_card_id = int(key)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid card ID key in batch {batch_number}: {key}") from error
            if tcgapi_card_id not in card_map:
                raise ValueError(
                    f"Batch {batch_number} returned unrequested card {tcgapi_card_id}."
                )
            returned_ids.add(tcgapi_card_id)
            if not isinstance(observations, list):
                raise ValueError(
                    f"History for card {tcgapi_card_id} must be an array."
                )
            if observations:
                cards_with_history.add(tcgapi_card_id)

            identity = card_map[tcgapi_card_id]
            for row_number, observation in enumerate(observations, start=1):
                if not isinstance(observation, dict):
                    raise ValueError("Every history observation must be an object.")
                try:
                    observation_date = date.fromisoformat(
                        _required_text(observation.get("date"), "history.date")
                    )
                except ValueError as error:
                    raise ValueError(
                        f"Invalid history date for card {tcgapi_card_id}."
                    ) from error
                printing = _required_text(
                    observation.get("printing"), "history.printing"
                )
                market_price = _optional_decimal(
                    observation.get("market_price"), "market_price"
                )
                low_price = _optional_decimal(
                    observation.get("low_price"), "low_price"
                )
                avg_sales_price = _optional_decimal(
                    observation.get("avg_sales_price"), "avg_sales_price"
                )
                sales_volume = _optional_nonnegative_int(
                    observation.get("sales_volume"), "sales_volume"
                )
                record_hash = _history_hash(
                    tcgapi_card_id,
                    observation_date,
                    printing,
                    market_price,
                    low_price,
                    avg_sales_price,
                    sales_volume,
                    config.source_name,
                    config.currency_code,
                )
                history_row = HistoryRow(
                    card_id=identity.card_id,
                    tcgapi_card_id=tcgapi_card_id,
                    observation_date=observation_date,
                    printing=printing,
                    market_price=market_price,
                    low_price=low_price,
                    avg_sales_price=avg_sales_price,
                    sales_volume=sales_volume,
                    source_name=config.source_name,
                    currency_code=config.currency_code,
                    source_file=_relative(raw_path),
                    source_row_number=row_number,
                    source_record_hash=record_hash,
                )
                existing = canonical_rows.get(history_row.canonical_key)
                if existing is not None:
                    if existing.source_record_hash == record_hash:
                        identical_duplicates += 1
                    else:
                        conflicting_duplicates.append(
                            {
                                "tcgapi_card_id": tcgapi_card_id,
                                "date": observation_date.isoformat(),
                                "printing": printing,
                                "earlier_hash": existing.source_record_hash,
                                "later_hash": record_hash,
                            }
                        )
                canonical_rows[history_row.canonical_key] = history_row
                batch_row_count += 1

        missing_ids = set(requested_ids) - returned_ids
        provider_omitted_ids.extend(sorted(missing_ids))

        batches.append(
            {
                "batch_number": batch_number,
                "requested_cards": len(requested_ids),
                "returned_card_keys": len(returned_ids),
                "provider_omitted_ids": sorted(missing_ids),
                "provider_rows": batch_row_count,
                "raw_file": _relative(raw_path),
            }
        )

    if conflicting_duplicates:
        raise ValueError(
            "Provider returned conflicting rows for "
            f"{len(conflicting_duplicates)} canonical history keys."
        )

    return list(canonical_rows.values()), {
        "requested_cards": len(cards),
        "cards_with_history": len(cards_with_history),
        "cards_without_history": len(cards) - len(cards_with_history),
        "provider_omitted_card_count": len(provider_omitted_ids),
        "provider_omitted_ids": provider_omitted_ids,
        "canonical_rows_received": len(canonical_rows),
        "identical_duplicate_rows": identical_duplicates,
        "conflicting_duplicate_rows": len(conflicting_duplicates),
        "conflicting_duplicate_details": conflicting_duplicates,
        "batches": batches,
    }


def load_history(
    config: HistoryConfig, rows: list[HistoryRow], selected_cards: list[CardIdentity]
) -> dict[str, Any]:
    selected_internal_ids = [card.card_id for card in selected_cards]
    incoming = {row.canonical_key: row for row in rows}

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT card_id, source_name, printing, currency_code,
                       observation_date, source_record_hash
                FROM price_history
                WHERE card_id = ANY(%s)
                  AND source_name = %s
                  AND currency_code = %s;
                """,
                (
                    selected_internal_ids,
                    config.source_name,
                    config.currency_code,
                ),
            )
            existing = {
                (card_id, source_name, printing, currency_code, observation_date): record_hash
                for card_id, source_name, printing, currency_code, observation_date, record_hash
                in cursor.fetchall()
            }

            inserted = 0
            unchanged = 0
            revisions: list[dict[str, Any]] = []
            for key, row in incoming.items():
                previous_hash = existing.get(key)
                if previous_hash is None:
                    inserted += 1
                elif previous_hash == row.source_record_hash:
                    unchanged += 1
                else:
                    revisions.append(
                        {
                            "tcgapi_card_id": row.tcgapi_card_id,
                            "date": row.observation_date.isoformat(),
                            "printing": row.printing,
                            "previous_hash": previous_hash,
                            "new_hash": row.source_record_hash,
                        }
                    )

            cursor.execute(
                """
                CREATE TEMP TABLE incoming_price_history ON COMMIT DROP AS
                SELECT
                    card_id, observation_date, printing, market_price, low_price,
                    avg_sales_price, sales_volume, source_name, currency_code,
                    source_file, source_row_number, source_record_hash
                FROM price_history
                WITH NO DATA;
                """
            )
            with cursor.copy(
                """
                COPY incoming_price_history (
                    card_id, observation_date, printing, market_price, low_price,
                    avg_sales_price, sales_volume, source_name, currency_code,
                    source_file, source_row_number, source_record_hash
                ) FROM STDIN
                """
            ) as copy:
                for row in rows:
                    copy.write_row(
                        (
                            row.card_id,
                            row.observation_date,
                            row.printing,
                            row.market_price,
                            row.low_price,
                            row.avg_sales_price,
                            row.sales_volume,
                            row.source_name,
                            row.currency_code,
                            row.source_file,
                            row.source_row_number,
                            row.source_record_hash,
                        )
                    )

            cursor.execute(
                """
                INSERT INTO price_history (
                    card_id, observation_date, printing, market_price, low_price,
                    avg_sales_price, sales_volume, source_name, currency_code,
                    source_file, source_row_number, source_record_hash
                )
                SELECT
                    card_id, observation_date, printing, market_price, low_price,
                    avg_sales_price, sales_volume, source_name, currency_code,
                    source_file, source_row_number, source_record_hash
                FROM incoming_price_history
                ON CONFLICT ON CONSTRAINT uq_price_history_canonical_observation
                DO UPDATE SET
                    market_price = EXCLUDED.market_price,
                    low_price = EXCLUDED.low_price,
                    avg_sales_price = EXCLUDED.avg_sales_price,
                    sales_volume = EXCLUDED.sales_volume,
                    source_file = EXCLUDED.source_file,
                    source_row_number = EXCLUDED.source_row_number,
                    source_record_hash = EXCLUDED.source_record_hash,
                    loaded_at = CURRENT_TIMESTAMP
                WHERE price_history.source_record_hash IS DISTINCT FROM
                      EXCLUDED.source_record_hash;
                """
            )

            cursor.execute(
                """
                SELECT count(*)
                FROM price_history
                WHERE card_id = ANY(%s)
                  AND source_name = %s
                  AND currency_code = %s;
                """,
                (
                    selected_internal_ids,
                    config.source_name,
                    config.currency_code,
                ),
            )
            database_rows = cursor.fetchone()[0]

    stale_existing_keys = set(existing) - set(incoming)
    return {
        "inserted_rows": inserted,
        "revised_rows": len(revisions),
        "unchanged_rows": unchanged,
        "existing_rows_not_returned": len(stale_existing_keys),
        "database_rows_after_load": database_rows,
        "revision_details": revisions,
    }


def write_history_manifest(
    path: Path,
    run_id: str,
    config: HistoryConfig,
    fetch_result: dict[str, Any],
    load_result: dict[str, Any],
) -> None:
    manifest = {
        "run_id": run_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source_name": config.source_name,
        "currency_code": config.currency_code,
        "history_range": config.history_range,
        **fetch_result,
        **load_result,
    }
    _write_json(path, manifest)

