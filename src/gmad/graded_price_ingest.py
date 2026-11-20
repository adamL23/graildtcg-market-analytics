"""Fetch once, replay, validate, and upsert aggregated graded summaries."""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import requests

from gmad.config import PROJECT_ROOT
from gmad.db import connect
from gmad.tcgapi_client import BASE_URL, TcgApiClient


RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "tcgapi_graded"


@dataclass(frozen=True)
class GradedPriceConfig:
    source_name: str
    currency_code: str
    include_mode: str
    expected_card_count: int
    credit_safety_buffer: int
    coverage_game_slugs: tuple[str, ...]
    source_set_keys: tuple[str, ...]


@dataclass(frozen=True)
class CardIdentity:
    card_id: int
    tcgapi_card_id: int
    tcgapi_set_id: int
    source_set_key: str
    set_name: str


@dataclass(frozen=True)
class GradedSummaryRow:
    card_id: int
    tcgapi_card_id: int
    printing: str
    grade_label: str
    median_30d: Decimal | None
    sales_30d: int
    last_sale_price: Decimal | None
    last_sold_date: date | None
    ungraded_days: int | None
    graded_days: int | None
    provider_as_of: date
    coverage_checked_at: datetime
    source_name: str
    currency_code: str
    source_file: str
    source_row_number: int
    source_record_hash: str

    @property
    def canonical_key(self) -> tuple[int, str, str, str, str]:
        return (
            self.card_id,
            self.source_name,
            self.currency_code,
            self.printing,
            self.grade_label,
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


def _optional_window_days(value: Any, field: str) -> int | None:
    if value is None:
        return None
    days = _nonnegative_int(value, field)
    if days > 30:
        raise ValueError(f"{field} cannot exceed 30.")
    return days


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


def _date(value: Any, field: str) -> date:
    text = _required_text(value, field)
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO date.") from error


def _optional_date(value: Any, field: str) -> date | None:
    if value is None:
        return None
    return _date(value, field)


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


def _record_hash(row: GradedSummaryRow) -> str:
    normalized = {
        "currency_code": row.currency_code,
        "grade_label": row.grade_label,
        "graded_days": row.graded_days,
        "last_sale_price": _decimal_for_hash(row.last_sale_price),
        "last_sold_date": (
            None if row.last_sold_date is None else row.last_sold_date.isoformat()
        ),
        "median_30d": _decimal_for_hash(row.median_30d),
        "printing": row.printing,
        "provider_as_of": row.provider_as_of.isoformat(),
        "sales_30d": row.sales_30d,
        "source_name": row.source_name,
        "tcgapi_card_id": row.tcgapi_card_id,
        "ungraded_days": row.ungraded_days,
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


def load_graded_price_config(path: Path) -> GradedPriceConfig:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    source_name = _required_text(payload.get("source_name"), "source_name")
    currency_code = _required_text(payload.get("currency_code"), "currency_code")
    if len(currency_code) != 3 or not currency_code.isupper():
        raise ValueError("currency_code must be three uppercase letters.")
    include_mode = _required_text(payload.get("include_mode"), "include_mode")
    if include_mode != "ebay":
        raise ValueError("Task 8 requires include_mode=ebay, never ebay_sales.")
    expected_card_count = _positive_int(
        payload.get("expected_card_count"), "expected_card_count"
    )
    credit_safety_buffer = _nonnegative_int(
        payload.get("credit_safety_buffer"), "credit_safety_buffer"
    )
    coverage_game_slugs = payload.get("coverage_game_slugs")
    source_set_keys = payload.get("source_set_keys")
    if not isinstance(coverage_game_slugs, list) or not coverage_game_slugs:
        raise ValueError("coverage_game_slugs must be a nonempty array.")
    if not isinstance(source_set_keys, list) or not source_set_keys:
        raise ValueError("source_set_keys must be a nonempty array.")
    return GradedPriceConfig(
        source_name=source_name,
        currency_code=currency_code,
        include_mode=include_mode,
        expected_card_count=expected_card_count,
        credit_safety_buffer=credit_safety_buffer,
        coverage_game_slugs=tuple(
            _required_text(item, "coverage_game_slugs item")
            for item in coverage_game_slugs
        ),
        source_set_keys=tuple(
            _required_text(item, "source_set_keys item") for item in source_set_keys
        ),
    )


def select_cards(config: GradedPriceConfig) -> list[CardIdentity]:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.card_id,
                    c.tcgapi_card_id,
                    s.tcgapi_set_id,
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


def fetch_graded_snapshot(
    client: TcgApiClient,
    config: GradedPriceConfig,
    cards: list[CardIdentity],
    run_directory: Path,
    run_id: str,
) -> dict[str, Any]:
    """Perform exactly one quota-gated full bulk request and preserve it."""

    target_set_ids = {card.tcgapi_set_id for card in cards}
    coverage_rows: dict[int, dict[str, Any]] = {}
    coverage_files: list[str] = []
    for slug in config.coverage_game_slugs:
        response = requests.get(
            f"{BASE_URL}/ebay/coverage", params={"game": slug}, timeout=30
        )
        response.raise_for_status()
        path = run_directory / f"coverage_{slug}.json"
        _write_raw(path, response.text)
        coverage_files.append(_relative(path))
        payload = json.loads(response.text)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("sets"), list):
            raise ValueError(f"Malformed public eBay coverage response for {slug}.")
        for item in data["sets"]:
            if isinstance(item, dict) and item.get("set_id") in target_set_ids:
                coverage_rows[int(item["set_id"])] = item

    if set(coverage_rows) != target_set_ids:
        missing = sorted(target_set_ids - set(coverage_rows))
        raise ValueError(f"Public eBay coverage omitted target sets: {missing}")
    projected_cards_with_any_ebay = sum(
        _nonnegative_int(item.get("cards_with_ebay"), "cards_with_ebay")
        for item in coverage_rows.values()
    )
    projected_credits = 1 + projected_cards_with_any_ebay

    probe_set_id = min(target_set_ids)
    probe_payload, probe_raw = client.get_json_with_raw(f"sets/{probe_set_id}")
    probe_path = run_directory / "quota_probe.json"
    _write_raw(probe_path, probe_raw)
    rate_limit = probe_payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise ValueError("Quota probe did not return rate_limit metadata.")
    available_credits = _nonnegative_int(
        rate_limit.get("daily_remaining"), "daily_remaining"
    )
    required_with_buffer = projected_credits + config.credit_safety_buffer
    if required_with_buffer > available_credits:
        gate_manifest = {
            "run_id": run_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "full_bulk_request_performed": False,
            "cards_requested": len(cards),
            "projected_cards_with_any_ebay": projected_cards_with_any_ebay,
            "projected_credits": projected_credits,
            "credit_safety_buffer": config.credit_safety_buffer,
            "available_credits_after_probe": available_credits,
            "reason": "Projected request plus safety buffer exceeds quota.",
            "coverage_files": coverage_files,
            "quota_probe_file": _relative(probe_path),
        }
        _write_json(run_directory / "request_manifest.json", gate_manifest)
        raise ValueError("Full graded request blocked by the credit safety gate.")

    card_ids = [card.tcgapi_card_id for card in cards]
    payload, raw_text = client.get_bulk_prices(card_ids, include=config.include_mode)
    captured_at = datetime.now(timezone.utc)
    raw_path = run_directory / "bulk_prices_ebay.json"
    _write_raw(raw_path, raw_text)
    data = payload.get("data")
    meta = payload.get("meta")
    if not isinstance(data, list) or not isinstance(meta, dict):
        raise ValueError("Malformed bulk graded-price response.")
    expected_ids = set(card_ids)
    returned_ids = {
        _positive_int(item.get("card_id"), "card_id")
        for item in data
        if isinstance(item, dict)
    }
    unknown_ids = returned_ids - expected_ids
    if unknown_ids:
        raise ValueError(f"Bulk prices returned unrequested cards: {sorted(unknown_ids)}")
    cards_with_any_ebay = {
        int(item["card_id"])
        for item in data
        if isinstance(item, dict) and isinstance(item.get("ebay"), dict)
    }
    cards_with_graded = {
        int(item["card_id"])
        for item in data
        if isinstance(item, dict)
        and isinstance(item.get("ebay"), dict)
        and bool(item["ebay"].get("graded"))
    }
    actual_credits = _positive_int(meta.get("credits_consumed"), "credits_consumed")
    manifest = {
        "run_id": run_id,
        "captured_at": captured_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source_name": config.source_name,
        "include_mode": config.include_mode,
        "full_bulk_request_performed": True,
        "full_bulk_request_count": 1,
        "cards_requested": len(cards),
        "projected_cards_with_any_ebay": projected_cards_with_any_ebay,
        "projected_credits": projected_credits,
        "credit_safety_buffer": config.credit_safety_buffer,
        "available_credits_after_probe": available_credits,
        "actual_credits_consumed": actual_credits,
        "cards_with_any_ebay": len(cards_with_any_ebay),
        "cards_with_graded_summaries": len(cards_with_graded),
        "price_rows_returned": len(data),
        "coverage_by_set": [coverage_rows[key] for key in sorted(coverage_rows)],
        "coverage_files": coverage_files,
        "quota_probe_file": _relative(probe_path),
        "raw_file": _relative(raw_path),
        "rate_limit_after_bulk": payload.get("rate_limit"),
    }
    _write_json(run_directory / "request_manifest.json", manifest)
    return manifest


def parse_graded_payload(
    payload: dict[str, Any],
    config: GradedPriceConfig,
    cards: list[CardIdentity],
    source_file: str,
    coverage_checked_at: datetime,
) -> tuple[list[GradedSummaryRow], dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Bulk graded payload data must be an array.")
    card_map = {card.tcgapi_card_id: card for card in cards}
    canonical: dict[tuple[int, str, str, str, str], GradedSummaryRow] = {}
    cards_with_any_ebay: set[int] = set()
    cards_with_graded: set[int] = set()
    grade_row_number = 0

    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Every bulk price row must be an object.")
        tcgapi_card_id = _positive_int(item.get("card_id"), "card_id")
        identity = card_map.get(tcgapi_card_id)
        if identity is None:
            raise ValueError(f"Bulk prices returned unknown card {tcgapi_card_id}.")
        ebay = item.get("ebay")
        if ebay is None:
            continue
        if not isinstance(ebay, dict):
            raise ValueError(f"Card {tcgapi_card_id} ebay value must be an object or null.")
        cards_with_any_ebay.add(tcgapi_card_id)
        graded = ebay.get("graded")
        if graded is None:
            graded = {}
        if not isinstance(graded, dict):
            raise ValueError(f"Card {tcgapi_card_id} ebay.graded must be an object.")
        if not graded:
            continue
        cards_with_graded.add(tcgapi_card_id)
        printing = _required_text(item.get("printing"), "printing")
        provider_as_of = _date(ebay.get("as_of"), "ebay.as_of")
        ungraded_days = _optional_window_days(ebay.get("days"), "ebay.days")
        graded_days = _optional_window_days(
            ebay.get("graded_days"), "ebay.graded_days"
        )

        for grade_label_value, summary in graded.items():
            grade_label = _required_text(grade_label_value, "grade_label")
            if not isinstance(summary, dict):
                raise ValueError(
                    f"Card {tcgapi_card_id} grade {grade_label} must be an object."
                )
            grade_row_number += 1
            row_without_hash = GradedSummaryRow(
                card_id=identity.card_id,
                tcgapi_card_id=tcgapi_card_id,
                printing=printing,
                grade_label=grade_label,
                median_30d=_optional_decimal(
                    summary.get("median_30d"), "grade.median_30d"
                ),
                sales_30d=_nonnegative_int(
                    summary.get("sales_30d"), "grade.sales_30d"
                ),
                last_sale_price=_optional_decimal(
                    summary.get("last_price"), "grade.last_price"
                ),
                last_sold_date=_optional_date(
                    summary.get("last_sold"), "grade.last_sold"
                ),
                ungraded_days=ungraded_days,
                graded_days=graded_days,
                provider_as_of=provider_as_of,
                coverage_checked_at=coverage_checked_at,
                source_name=config.source_name,
                currency_code=config.currency_code,
                source_file=source_file,
                source_row_number=grade_row_number,
                source_record_hash="",
            )
            row = replace(
                row_without_hash,
                source_record_hash=_record_hash(row_without_hash),
            )
            if row.canonical_key in canonical:
                raise ValueError(
                    "Duplicate canonical graded key for card "
                    f"{tcgapi_card_id}, {printing}, {grade_label}."
                )
            canonical[row.canonical_key] = row

    rows = list(canonical.values())
    labels = Counter(row.grade_label for row in rows)
    return rows, {
        "cards_requested": len(cards),
        "cards_with_any_ebay": len(cards_with_any_ebay),
        "cards_with_graded_summaries": len(cards_with_graded),
        "cards_without_any_ebay": len(cards) - len(cards_with_any_ebay),
        "cards_with_ebay_but_no_graded_summaries": len(
            cards_with_any_ebay - cards_with_graded
        ),
        "canonical_graded_rows": len(rows),
        "raw_grade_labels": dict(sorted(labels.items())),
        "median_30d_nulls": sum(row.median_30d is None for row in rows),
        "median_null_with_historical_last_sale": sum(
            row.median_30d is None
            and row.last_sale_price is not None
            and row.last_sold_date is not None
            for row in rows
        ),
        "complete_graded_windows": sum(row.graded_days == 30 for row in rows),
        "partial_or_unknown_graded_windows": sum(
            row.graded_days != 30 for row in rows
        ),
        "ungraded_days_values": dict(
            sorted(Counter(str(row.ungraded_days) for row in rows).items())
        ),
        "graded_days_values": dict(
            sorted(Counter(str(row.graded_days) for row in rows).items())
        ),
    }


def read_saved_graded_snapshot(
    config: GradedPriceConfig,
    cards: list[CardIdentity],
    run_directory: Path,
) -> tuple[list[GradedSummaryRow], dict[str, Any], datetime]:
    request_manifest_path = run_directory / "request_manifest.json"
    raw_path = run_directory / "bulk_prices_ebay.json"
    with request_manifest_path.open("r", encoding="utf-8") as file:
        request_manifest = json.load(file)
    if request_manifest.get("full_bulk_request_performed") is not True:
        raise ValueError("The selected run has no completed full bulk request.")
    if request_manifest.get("full_bulk_request_count") != 1:
        raise ValueError("Task 8 requires exactly one full bulk request per run.")
    coverage_checked_at = _timestamp(
        request_manifest.get("captured_at"), "captured_at"
    )
    with raw_path.open("r", encoding="utf-8") as file:
        payload = json.load(file, parse_float=Decimal)
    rows, parse_result = parse_graded_payload(
        payload,
        config,
        cards,
        _relative(raw_path),
        coverage_checked_at,
    )
    return rows, {**request_manifest, **parse_result}, coverage_checked_at


def load_graded_summaries(
    config: GradedPriceConfig,
    rows: list[GradedSummaryRow],
    selected_cards: list[CardIdentity],
    coverage_checked_at: datetime,
) -> dict[str, Any]:
    selected_card_ids = [card.card_id for card in selected_cards]
    incoming = {row.canonical_key: row for row in rows}

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    card_id, source_name, currency_code, printing, grade_label,
                    provider_as_of, source_record_hash, coverage_checked_at,
                    is_reported_in_latest_snapshot
                FROM graded_price_summaries
                WHERE card_id = ANY(%s)
                  AND source_name = %s
                  AND currency_code = %s;
                """,
                (selected_card_ids, config.source_name, config.currency_code),
            )
            existing = {
                (card_id, source_name, currency_code, printing, grade_label): (
                    provider_as_of,
                    source_record_hash,
                    previous_coverage_checked_at,
                    is_reported,
                )
                for (
                    card_id,
                    source_name,
                    currency_code,
                    printing,
                    grade_label,
                    provider_as_of,
                    source_record_hash,
                    previous_coverage_checked_at,
                    is_reported,
                ) in cursor.fetchall()
            }

            inserted = 0
            updated_newer = 0
            revised_same_date = 0
            unchanged = 0
            older_source_rows_skipped = 0
            for key, row in incoming.items():
                previous = existing.get(key)
                if previous is None:
                    inserted += 1
                    continue
                previous_as_of, previous_hash, previous_checked_at, _ = previous
                if coverage_checked_at < previous_checked_at:
                    older_source_rows_skipped += 1
                elif row.provider_as_of < previous_as_of:
                    older_source_rows_skipped += 1
                elif row.provider_as_of == previous_as_of:
                    if row.source_record_hash == previous_hash:
                        unchanged += 1
                    else:
                        revised_same_date += 1
                else:
                    updated_newer += 1

            cursor.execute(
                """
                CREATE TEMP TABLE incoming_graded_summaries ON COMMIT DROP AS
                SELECT
                    card_id, printing, grade_label, median_30d, sales_30d,
                    last_sale_price, last_sold_date, ungraded_days, graded_days,
                    provider_as_of, coverage_checked_at, source_name,
                    currency_code, source_file, source_row_number,
                    source_record_hash
                FROM graded_price_summaries
                WITH NO DATA;
                """
            )
            with cursor.copy(
                """
                COPY incoming_graded_summaries (
                    card_id, printing, grade_label, median_30d, sales_30d,
                    last_sale_price, last_sold_date, ungraded_days, graded_days,
                    provider_as_of, coverage_checked_at, source_name,
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
                            row.grade_label,
                            row.median_30d,
                            row.sales_30d,
                            row.last_sale_price,
                            row.last_sold_date,
                            row.ungraded_days,
                            row.graded_days,
                            row.provider_as_of,
                            row.coverage_checked_at,
                            row.source_name,
                            row.currency_code,
                            row.source_file,
                            row.source_row_number,
                            row.source_record_hash,
                        )
                    )

            cursor.execute(
                """
                INSERT INTO graded_price_summaries (
                    card_id, printing, grade_label, median_30d, sales_30d,
                    last_sale_price, last_sold_date, ungraded_days, graded_days,
                    provider_as_of, coverage_checked_at, source_name,
                    currency_code, source_file, source_row_number,
                    source_record_hash
                )
                SELECT
                    card_id, printing, grade_label, median_30d, sales_30d,
                    last_sale_price, last_sold_date, ungraded_days, graded_days,
                    provider_as_of, coverage_checked_at, source_name,
                    currency_code, source_file, source_row_number,
                    source_record_hash
                FROM incoming_graded_summaries
                ON CONFLICT ON CONSTRAINT
                    uq_graded_price_summaries_canonical_snapshot
                DO NOTHING;
                """
            )

            cursor.execute(
                """
                UPDATE graded_price_summaries AS stored
                SET
                    median_30d = incoming.median_30d,
                    sales_30d = incoming.sales_30d,
                    last_sale_price = incoming.last_sale_price,
                    last_sold_date = incoming.last_sold_date,
                    ungraded_days = incoming.ungraded_days,
                    graded_days = incoming.graded_days,
                    provider_as_of = incoming.provider_as_of,
                    is_reported_in_latest_snapshot = TRUE,
                    coverage_checked_at = incoming.coverage_checked_at,
                    source_file = incoming.source_file,
                    source_row_number = incoming.source_row_number,
                    source_record_hash = incoming.source_record_hash,
                    loaded_at = CURRENT_TIMESTAMP
                FROM incoming_graded_summaries AS incoming
                WHERE stored.card_id = incoming.card_id
                  AND stored.source_name = incoming.source_name
                  AND stored.currency_code = incoming.currency_code
                  AND stored.printing = incoming.printing
                  AND stored.grade_label = incoming.grade_label
                  AND incoming.coverage_checked_at >= stored.coverage_checked_at
                  AND (
                      incoming.provider_as_of > stored.provider_as_of
                      OR (
                          incoming.provider_as_of = stored.provider_as_of
                          AND stored.source_record_hash IS DISTINCT FROM
                              incoming.source_record_hash
                      )
                  );
                """
            )

            cursor.execute(
                """
                UPDATE graded_price_summaries AS stored
                SET
                    is_reported_in_latest_snapshot = TRUE,
                    coverage_checked_at = incoming.coverage_checked_at,
                    source_file = incoming.source_file,
                    source_row_number = incoming.source_row_number,
                    loaded_at = CURRENT_TIMESTAMP
                FROM incoming_graded_summaries AS incoming
                WHERE stored.card_id = incoming.card_id
                  AND stored.source_name = incoming.source_name
                  AND stored.currency_code = incoming.currency_code
                  AND stored.printing = incoming.printing
                  AND stored.grade_label = incoming.grade_label
                  AND incoming.coverage_checked_at > stored.coverage_checked_at;
                """
            )

            cursor.execute(
                """
                UPDATE graded_price_summaries AS stored
                SET
                    is_reported_in_latest_snapshot = FALSE,
                    coverage_checked_at = %s,
                    loaded_at = CURRENT_TIMESTAMP
                WHERE stored.card_id = ANY(%s)
                  AND stored.source_name = %s
                  AND stored.currency_code = %s
                  AND stored.coverage_checked_at < %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM incoming_graded_summaries AS incoming
                      WHERE incoming.card_id = stored.card_id
                        AND incoming.source_name = stored.source_name
                        AND incoming.currency_code = stored.currency_code
                        AND incoming.printing = stored.printing
                        AND incoming.grade_label = stored.grade_label
                  );
                """,
                (
                    coverage_checked_at,
                    selected_card_ids,
                    config.source_name,
                    config.currency_code,
                    coverage_checked_at,
                ),
            )
            retained_marked_last_known = cursor.rowcount

            cursor.execute(
                """
                SELECT
                    count(*),
                    count(*) FILTER (WHERE is_reported_in_latest_snapshot)
                FROM graded_price_summaries
                WHERE card_id = ANY(%s)
                  AND source_name = %s
                  AND currency_code = %s;
                """,
                (selected_card_ids, config.source_name, config.currency_code),
            )
            database_rows, currently_reported_rows = cursor.fetchone()

    return {
        "inserted_rows": inserted,
        "updated_from_newer_provider_date": updated_newer,
        "revised_at_same_provider_date": revised_same_date,
        "unchanged_rows": unchanged,
        "older_source_rows_skipped": older_source_rows_skipped,
        "existing_rows_not_returned": len(set(existing) - set(incoming)),
        "retained_rows_marked_last_known": retained_marked_last_known,
        "database_rows_after_load": database_rows,
        "currently_reported_rows_after_load": currently_reported_rows,
        "last_known_rows_after_load": database_rows - currently_reported_rows,
    }


def write_load_manifest(
    path: Path,
    run_id: str,
    parse_result: dict[str, Any],
    load_result: dict[str, Any],
) -> None:
    manifest = {
        "run_id": run_id,
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        **parse_result,
        **load_result,
    }
    _write_json(path, manifest)
