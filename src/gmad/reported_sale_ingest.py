"""Controlled extraction and immutable replay of provider sale observations."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any

import requests

from gmad.config import PROJECT_ROOT
from gmad.db import connect
from gmad.tcgapi_client import BASE_URL, TcgApiClient


RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "tcgapi_sales"


class DataIntegrityError(RuntimeError):
    """Raised when an immutable source snapshot conflicts with stored data."""


@dataclass(frozen=True)
class ReportedSaleConfig:
    source_name: str
    include_mode: str
    eligibility_snapshot: Path
    expected_card_count: int
    credit_safety_buffer: int
    hard_credit_spend_ceiling: int
    estimated_credit_per_card_attempt: int
    estimated_quota_probe_credit: int
    max_workers: int
    max_attempts_per_card: int
    request_timeout_seconds: int
    retry_backoff_seconds: tuple[int, ...]


@dataclass(frozen=True)
class EligibleCard:
    card_id: int
    tcgapi_card_id: int
    tcgapi_set_id: int
    source_set_key: str
    set_name: str


@dataclass(frozen=True)
class ReportedSaleObservation:
    source_snapshot_key: str
    card_id: int
    tcgapi_card_id: int
    printing: str
    source_row_number: int
    sold_date: date | None
    price: Decimal | None
    best_offer: bool | None
    list_price: Decimal | None
    grade_label: str | None
    condition_label: str | None
    listing_title: str | None
    listing_url: str | None
    currency_code: str | None
    provider_as_of: date | None
    source_captured_at: datetime
    source_name: str
    source_file: str
    source_record_hash: str

    @property
    def replay_key(self) -> tuple[str, int, str, int]:
        return (
            self.source_snapshot_key,
            self.card_id,
            self.printing,
            self.source_row_number,
        )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string.")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null.")
    return value


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer.")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer.")
    return value


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean or null.")
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
    text = _required_text(value, field)
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO date or null.") from error


def _timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be a valid ISO timestamp.") from error
    if result.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return result


def _write_raw(path: Path, raw_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(raw_text)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")
    # OneDrive can briefly hold the destination during synchronization. Keep the
    # atomic replacement semantics, but tolerate that short local lock rather
    # than losing already-persisted card responses.
    last_error: PermissionError | None = None
    for _ in range(50):
        try:
            temporary.replace(path)
            return
        except PermissionError as error:
            last_error = error
            time.sleep(0.1)
    if last_error is not None:
        raise last_error


def _relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def _normalized_for_hash(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, dict):
        return {
            str(key): _normalized_for_hash(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_normalized_for_hash(item) for item in value]
    return value


def _observation_hash(
    source_snapshot_key: str,
    tcgapi_card_id: int,
    printing: str,
    source_row_number: int,
    provider_as_of: date | None,
    sale: dict[str, Any],
) -> str:
    normalized = {
        "provider_as_of": (
            None if provider_as_of is None else provider_as_of.isoformat()
        ),
        "provider_observation": _normalized_for_hash(sale),
        "replay_key": {
            "source_snapshot_key": source_snapshot_key,
            "tcgapi_card_id": tcgapi_card_id,
            "printing": printing,
            "source_row_number": source_row_number,
        },
    }
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def load_reported_sale_config(path: Path) -> ReportedSaleConfig:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    source_name = _required_text(payload.get("source_name"), "source_name")
    include_mode = _required_text(payload.get("include_mode"), "include_mode")
    if include_mode != "ebay_sales":
        raise ValueError("Task 9 requires include_mode=ebay_sales.")
    eligibility_value = _required_text(
        payload.get("eligibility_snapshot"), "eligibility_snapshot"
    )
    eligibility_snapshot = (PROJECT_ROOT / eligibility_value).resolve()
    if not eligibility_snapshot.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("eligibility_snapshot must remain inside the project.")
    if not eligibility_snapshot.is_file():
        raise ValueError(f"Eligibility snapshot does not exist: {eligibility_value}")
    retry_values = payload.get("retry_backoff_seconds")
    if not isinstance(retry_values, list):
        raise ValueError("retry_backoff_seconds must be an array.")
    retry_backoff_seconds = tuple(
        _nonnegative_int(value, "retry_backoff_seconds item")
        for value in retry_values
    )
    config = ReportedSaleConfig(
        source_name=source_name,
        include_mode=include_mode,
        eligibility_snapshot=eligibility_snapshot,
        expected_card_count=_positive_int(
            payload.get("expected_card_count"), "expected_card_count"
        ),
        credit_safety_buffer=_nonnegative_int(
            payload.get("credit_safety_buffer"), "credit_safety_buffer"
        ),
        hard_credit_spend_ceiling=_positive_int(
            payload.get("hard_credit_spend_ceiling"),
            "hard_credit_spend_ceiling",
        ),
        estimated_credit_per_card_attempt=_positive_int(
            payload.get("estimated_credit_per_card_attempt"),
            "estimated_credit_per_card_attempt",
        ),
        estimated_quota_probe_credit=_positive_int(
            payload.get("estimated_quota_probe_credit"),
            "estimated_quota_probe_credit",
        ),
        max_workers=_positive_int(payload.get("max_workers"), "max_workers"),
        max_attempts_per_card=_positive_int(
            payload.get("max_attempts_per_card"), "max_attempts_per_card"
        ),
        request_timeout_seconds=_positive_int(
            payload.get("request_timeout_seconds"), "request_timeout_seconds"
        ),
        retry_backoff_seconds=retry_backoff_seconds,
    )
    if config.max_workers > 4:
        raise ValueError("Task 9 max_workers cannot exceed four.")
    if config.max_attempts_per_card > 3:
        raise ValueError("Task 9 max_attempts_per_card cannot exceed three.")
    baseline = config.expected_card_count * config.estimated_credit_per_card_attempt
    if baseline + config.estimated_quota_probe_credit > config.hard_credit_spend_ceiling:
        raise ValueError("Hard credit ceiling is below the baseline extraction cost.")
    return config


def select_eligible_cards(
    config: ReportedSaleConfig,
) -> tuple[list[EligibleCard], dict[str, Any]]:
    with config.eligibility_snapshot.open("r", encoding="utf-8") as file:
        eligibility = json.load(file)
    raw_ids = eligibility.get("eligible_tcgapi_card_ids")
    if not isinstance(raw_ids, list):
        raise ValueError("Eligibility snapshot card IDs must be an array.")
    ids = [_positive_int(value, "eligible_tcgapi_card_ids item") for value in raw_ids]
    if len(ids) != config.expected_card_count or len(set(ids)) != len(ids):
        raise ValueError("Eligibility snapshot count or uniqueness is invalid.")
    if eligibility.get("eligible_card_count") != config.expected_card_count:
        raise ValueError("Eligibility snapshot declared count does not match config.")
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.card_id, c.tcgapi_card_id, s.tcgapi_set_id,
                    s.source_set_key, s.set_name
                FROM cards AS c
                JOIN sets AS s ON s.set_id = c.set_id
                WHERE c.tcgapi_card_id = ANY(%s)
                ORDER BY c.tcgapi_card_id;
                """,
                (ids,),
            )
            cards = [EligibleCard(*row) for row in cursor.fetchall()]
    returned_ids = {card.tcgapi_card_id for card in cards}
    if returned_ids != set(ids):
        missing = sorted(set(ids) - returned_ids)
        raise ValueError(f"Eligibility snapshot contains unknown cards: {missing}")
    return cards, eligibility


def _eligible_ids_hash(cards: list[EligibleCard]) -> str:
    encoded = ",".join(str(card.tcgapi_card_id) for card in cards).encode("ascii")
    return sha256(encoded).hexdigest()


def _add_manifest_diagnostics(
    manifest: dict[str, Any], config: ReportedSaleConfig
) -> None:
    """Keep API, quota, and local persistence outcomes explicitly separate."""

    errors = [
        error
        for state in manifest.get("cards", {}).values()
        for error in state.get("attempt_errors", [])
        if isinstance(error, dict)
    ]
    rate_remaining = [
        state.get("rate_limit", {}).get("daily_remaining")
        for state in manifest.get("cards", {}).values()
        if isinstance(state.get("rate_limit"), dict)
        and isinstance(state.get("rate_limit", {}).get("daily_remaining"), int)
    ]
    manifest["provider_reported_card_credits_consumed"] = int(
        manifest.get("reported_card_credits", 0)
    )
    manifest["quota_probe_count"] = len(manifest.get("quota_probes", []))
    manifest["estimated_quota_probe_credits_reserved"] = (
        manifest["quota_probe_count"] * config.estimated_quota_probe_credit
    )
    manifest["hard_credit_ceiling_remaining"] = (
        config.hard_credit_spend_ceiling
        - int(manifest.get("estimated_credits_reserved_including_probes", 0))
    )
    manifest["api_failure_count"] = sum(
        error.get("category") in {"http_error", "network_error"}
        for error in errors
    )
    manifest["quota_exhaustion_count"] = sum(
        error.get("status_code") == 429 for error in errors
    )
    manifest["local_persistence_error_count"] = sum(
        error.get("category") == "worker_error" for error in errors
    )
    manifest["latest_provider_daily_remaining"] = (
        min(rate_remaining) if rate_remaining else None
    )


def _inspect_card_payload(payload: dict[str, Any], tcgapi_card_id: int) -> dict[str, int]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Successful response data must be an array.")
    seen_printings: set[str] = set()
    sales_arrays = 0
    missing_sales_arrays = 0
    empty_sales_arrays = 0
    observation_rows = 0
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Every price row must be an object.")
        returned_id = _positive_int(item.get("card_id"), "card_id")
        if returned_id != tcgapi_card_id:
            raise ValueError(
                f"Card {tcgapi_card_id} response contained card {returned_id}."
            )
        printing = _required_text(item.get("printing"), "printing")
        if printing in seen_printings:
            raise ValueError(
                f"Card {tcgapi_card_id} repeated printing {printing!r}; row identity is ambiguous."
            )
        seen_printings.add(printing)
        ebay = item.get("ebay")
        if not isinstance(ebay, dict) or not isinstance(ebay.get("sales"), list):
            missing_sales_arrays += 1
            continue
        sales = ebay["sales"]
        sales_arrays += 1
        if not sales:
            empty_sales_arrays += 1
        for sale in sales:
            if not isinstance(sale, dict):
                raise ValueError("Every sale observation must be an object.")
        observation_rows += len(sales)
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("Successful response meta must be an object.")
    credits = _positive_int(meta.get("credits_consumed"), "meta.credits_consumed")
    return {
        "price_rows": len(data),
        "sales_arrays": sales_arrays,
        "missing_sales_arrays": missing_sales_arrays,
        "empty_sales_arrays": empty_sales_arrays,
        "observation_rows": observation_rows,
        "reported_credits": credits,
    }


def fetch_reported_sales_snapshot(
    config: ReportedSaleConfig,
    cards: list[EligibleCard],
    eligibility: dict[str, Any],
    run_directory: Path,
    run_id: str,
    resume: bool,
) -> dict[str, Any]:
    """Fetch each eligible card once, with bounded retries and durable progress."""

    manifest_path = run_directory / "request_manifest.json"
    lock = Lock()
    if resume:
        if not manifest_path.is_file():
            raise ValueError(f"Cannot resume missing run {run_id}.")
        with manifest_path.open("r", encoding="utf-8") as file:
            manifest = json.load(file)
        if manifest.get("run_id") != run_id:
            raise DataIntegrityError("Resume manifest run ID does not match directory.")
        if manifest.get("eligible_ids_hash") != _eligible_ids_hash(cards):
            raise DataIntegrityError("Resume eligibility differs from the immutable run.")
        if manifest.get("status") == "complete":
            _add_manifest_diagnostics(manifest, config)
            _write_json_atomic(manifest_path, manifest)
            return {**manifest, "manifest_file": _relative(manifest_path)}
        # A process can be interrupted after an HTTP 200 body is durably saved
        # but before the manifest rename succeeds. Recover those exact files and
        # never issue a duplicate provider request for them.
        recovered_responses = 0
        for card in cards:
            key = str(card.tcgapi_card_id)
            state = manifest["cards"].get(key, {})
            if state.get("status") == "success":
                continue
            raw_path = run_directory / "cards" / f"card_{card.tcgapi_card_id}.json"
            if not raw_path.is_file():
                continue
            try:
                with raw_path.open("r", encoding="utf-8") as file:
                    payload = json.load(file, parse_float=Decimal)
                if not isinstance(payload, dict):
                    raise ValueError("Recovered response must be a JSON object.")
                inspected = _inspect_card_payload(payload, card.tcgapi_card_id)
            except Exception as error:
                state["status"] = "invalid_saved_response"
                state.setdefault("attempt_errors", []).append(
                    {
                        "category": "invalid_saved_response",
                        "message": str(error),
                        "raw_file": _relative(raw_path),
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                manifest["cards"][key] = state
                continue
            captured_at = datetime.fromtimestamp(
                raw_path.stat().st_mtime, tz=timezone.utc
            )
            state.update(
                {
                    "status": "success",
                    "captured_at": captured_at.isoformat(),
                    "raw_file": _relative(raw_path),
                    **inspected,
                    "rate_limit": payload.get("rate_limit"),
                    "recovered_from_saved_raw_response": True,
                }
            )
            manifest["cards"][key] = state
            recovered_responses += 1
        manifest["recovered_saved_response_count"] = (
            int(manifest.get("recovered_saved_response_count", 0))
            + recovered_responses
        )
        manifest["reported_card_credits"] = sum(
            int(state.get("reported_credits", 0))
            for state in manifest["cards"].values()
            if state.get("status") == "success"
        )
        _write_json_atomic(manifest_path, manifest)
    else:
        if run_directory.exists():
            raise ValueError(f"New extraction directory already exists: {run_id}")
        run_directory.mkdir(parents=True)
        eligibility_copy = run_directory / "eligibility_snapshot.json"
        _write_json_atomic(eligibility_copy, eligibility)
        baseline = len(cards) * config.estimated_credit_per_card_attempt
        manifest = {
            "run_id": run_id,
            "source_snapshot_key": f"{config.source_name}:ebay_sales:{run_id}",
            "status": "initialized",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "source_name": config.source_name,
            "include_mode": config.include_mode,
            "eligibility_source_file": _relative(config.eligibility_snapshot),
            "eligibility_snapshot_file": _relative(eligibility_copy),
            "eligibility_source_task8_run_id": eligibility.get("source_task8_run_id"),
            "eligibility_rule": eligibility.get("eligibility_rule"),
            "eligible_card_count": len(cards),
            "eligible_ids_hash": _eligible_ids_hash(cards),
            "baseline_projected_card_credits": baseline,
            "credit_safety_buffer": config.credit_safety_buffer,
            "hard_credit_spend_ceiling": config.hard_credit_spend_ceiling,
            "estimated_credit_per_card_attempt": config.estimated_credit_per_card_attempt,
            "estimated_quota_probe_credit": config.estimated_quota_probe_credit,
            "max_workers": config.max_workers,
            "max_attempts_per_card": config.max_attempts_per_card,
            "quota_probes": [],
            "estimated_credits_reserved_including_probes": 0,
            "reported_card_credits": 0,
            "cards": {},
            "successful_card_count": 0,
            "failed_card_count": 0,
            "failure_summary": {},
            "full_extraction_performed": False,
        }
        _write_json_atomic(manifest_path, manifest)

    def persist() -> None:
        manifest["successful_card_count"] = sum(
            row.get("status") == "success" for row in manifest["cards"].values()
        )
        manifest["failed_card_count"] = sum(
            row.get("status") not in {"success", "pending"}
            for row in manifest["cards"].values()
        )
        _write_json_atomic(manifest_path, manifest)

    # Every authenticated attempt is reserved pessimistically before it is sent.
    with lock:
        next_reserved = (
            manifest["estimated_credits_reserved_including_probes"]
            + config.estimated_quota_probe_credit
        )
        if next_reserved > config.hard_credit_spend_ceiling:
            raise ValueError("Quota probe would exceed the hard credit ceiling.")
        manifest["estimated_credits_reserved_including_probes"] = next_reserved
        probe_number = len(manifest["quota_probes"]) + 1
        persist()
    probe_client = TcgApiClient(timeout_seconds=config.request_timeout_seconds)
    probe_set_id = min(card.tcgapi_set_id for card in cards)
    try:
        probe_payload, probe_raw = probe_client.get_json_with_raw(f"sets/{probe_set_id}")
    except Exception as error:
        with lock:
            manifest["status"] = "incomplete_quota_probe_failed"
            manifest["failure_summary"]["quota_probe"] = str(error)
            persist()
        raise
    probe_path = run_directory / f"quota_probe_{probe_number}.json"
    _write_raw(probe_path, probe_raw)
    rate_limit = probe_payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise ValueError("Quota probe response is missing rate_limit metadata.")
    daily_remaining = _nonnegative_int(
        rate_limit.get("daily_remaining"), "rate_limit.daily_remaining"
    )
    completed_ids = {
        int(card_id)
        for card_id, row in manifest["cards"].items()
        if row.get("status") in {"success", "invalid_response"}
    }
    remaining_cards = len(cards) - len(completed_ids)
    remaining_baseline = remaining_cards * config.estimated_credit_per_card_attempt
    with lock:
        manifest["quota_probes"].append(
            {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "raw_file": _relative(probe_path),
                "daily_remaining": daily_remaining,
                "daily_limit": rate_limit.get("daily_limit"),
                "daily_reset": rate_limit.get("daily_reset"),
                "estimated_credit_reserved": config.estimated_quota_probe_credit,
            }
        )
        if remaining_baseline + config.credit_safety_buffer > daily_remaining:
            manifest["status"] = "incomplete_quota_gate_blocked"
            manifest["failure_summary"]["quota_gate"] = (
                "Remaining baseline plus safety buffer exceeds provider quota."
            )
            persist()
            raise ValueError("Extraction blocked by the provider quota safety gate.")
        if (
            manifest["estimated_credits_reserved_including_probes"]
            + remaining_baseline
            > config.hard_credit_spend_ceiling
        ):
            manifest["status"] = "incomplete_hard_credit_gate_blocked"
            manifest["failure_summary"]["hard_credit_gate"] = (
                "Remaining baseline exceeds the configured hard credit ceiling."
            )
            persist()
            raise ValueError("Extraction blocked by the hard credit-spend ceiling.")
        manifest["status"] = "extracting"
        manifest["full_extraction_performed"] = True
        persist()

    card_map = {card.tcgapi_card_id: card for card in cards}

    def reserve_attempt(card_id: int) -> int | None:
        with lock:
            key = str(card_id)
            state = manifest["cards"].setdefault(
                key, {"status": "pending", "attempts": 0, "attempt_errors": []}
            )
            if state.get("status") in {"success", "invalid_response"}:
                return None
            if state["attempts"] >= config.max_attempts_per_card:
                state["status"] = "attempt_limit_exhausted"
                persist()
                return None
            next_reserved = (
                manifest["estimated_credits_reserved_including_probes"]
                + config.estimated_credit_per_card_attempt
            )
            if next_reserved > config.hard_credit_spend_ceiling:
                state["status"] = "hard_credit_ceiling_reached"
                manifest["failure_summary"]["hard_credit_ceiling"] = (
                    "At least one card was not attempted because the ceiling was reached."
                )
                persist()
                return None
            state["attempts"] += 1
            attempt = state["attempts"]
            state["status"] = "requesting"
            manifest["estimated_credits_reserved_including_probes"] = next_reserved
            persist()
            return attempt

    def record_attempt_error(
        card_id: int,
        attempt: int,
        category: str,
        message: str,
        retryable: bool,
        status_code: int | None = None,
        raw_file: str | None = None,
    ) -> None:
        with lock:
            state = manifest["cards"][str(card_id)]
            error_row = {
                "attempt": attempt,
                "category": category,
                "message": message,
                "retryable": retryable,
                "status_code": status_code,
                "raw_file": raw_file,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            state["attempt_errors"].append(error_row)
            state["status"] = "retry_pending" if retryable else category
            persist()

    def fetch_one(card_id: int) -> None:
        state = manifest["cards"].get(str(card_id))
        if state and state.get("status") in {"success", "invalid_response"}:
            return
        while True:
            attempt = reserve_attempt(card_id)
            if attempt is None:
                return
            client = TcgApiClient(timeout_seconds=config.request_timeout_seconds)
            try:
                response = client.session.get(
                    f"{BASE_URL}/cards/{card_id}/prices",
                    params={"include": config.include_mode},
                    timeout=config.request_timeout_seconds,
                )
            except requests.RequestException as error:
                retryable = attempt < config.max_attempts_per_card
                record_attempt_error(
                    card_id, attempt, "network_error", str(error), retryable
                )
                if retryable:
                    delay_index = min(attempt - 1, len(config.retry_backoff_seconds) - 1)
                    if config.retry_backoff_seconds:
                        time.sleep(config.retry_backoff_seconds[delay_index])
                    continue
                return

            if response.status_code == 200:
                raw_path = run_directory / "cards" / f"card_{card_id}.json"
                _write_raw(raw_path, response.text)
                captured_at = datetime.now(timezone.utc)
                try:
                    payload = json.loads(response.text, parse_float=Decimal)
                    if not isinstance(payload, dict):
                        raise ValueError("Successful response must be a JSON object.")
                    inspected = _inspect_card_payload(payload, card_id)
                except Exception as error:
                    record_attempt_error(
                        card_id,
                        attempt,
                        "invalid_response",
                        str(error),
                        False,
                        status_code=200,
                        raw_file=_relative(raw_path),
                    )
                    return
                with lock:
                    current = manifest["cards"][str(card_id)]
                    current.update(
                        {
                            "status": "success",
                            "captured_at": captured_at.isoformat(),
                            "raw_file": _relative(raw_path),
                            **inspected,
                            "rate_limit": payload.get("rate_limit"),
                        }
                    )
                    manifest["reported_card_credits"] += inspected[
                        "reported_credits"
                    ]
                    persist()
                return

            error_path = (
                run_directory
                / "errors"
                / f"card_{card_id}_attempt_{attempt}_http_{response.status_code}.txt"
            )
            _write_raw(error_path, response.text)
            retryable = (
                response.status_code == 429 or response.status_code >= 500
            ) and attempt < config.max_attempts_per_card
            record_attempt_error(
                card_id,
                attempt,
                "http_error",
                f"HTTP {response.status_code}",
                retryable,
                status_code=response.status_code,
                raw_file=_relative(error_path),
            )
            if retryable:
                delay_index = min(attempt - 1, len(config.retry_backoff_seconds) - 1)
                if config.retry_backoff_seconds:
                    time.sleep(config.retry_backoff_seconds[delay_index])
                continue
            return

    pending_ids = [
        card.tcgapi_card_id
        for card in cards
        if manifest["cards"].get(str(card.tcgapi_card_id), {}).get("status")
        not in {"success", "invalid_response"}
    ]
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        futures = {executor.submit(fetch_one, card_id): card_id for card_id in pending_ids}
        for future in as_completed(futures):
            card_id = futures[future]
            try:
                future.result()
            except Exception as error:
                with lock:
                    state = manifest["cards"].setdefault(
                        str(card_id),
                        {"status": "worker_error", "attempts": 0, "attempt_errors": []},
                    )
                    state["status"] = "worker_error"
                    state["attempt_errors"].append(
                        {
                            "category": "worker_error",
                            "message": str(error),
                            "recorded_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    persist()

    with lock:
        successful = sum(
            row.get("status") == "success" for row in manifest["cards"].values()
        )
        status_counts: dict[str, int] = {}
        for row in manifest["cards"].values():
            status = str(row.get("status"))
            status_counts[status] = status_counts.get(status, 0) + 1
        manifest["status_counts"] = dict(sorted(status_counts.items()))
        manifest["missing_sales_array_price_rows"] = sum(
            int(row.get("missing_sales_arrays", 0))
            for row in manifest["cards"].values()
            if row.get("status") == "success"
        )
        manifest["empty_sales_array_price_rows"] = sum(
            int(row.get("empty_sales_arrays", 0))
            for row in manifest["cards"].values()
            if row.get("status") == "success"
        )
        manifest["reported_observation_rows"] = sum(
            int(row.get("observation_rows", 0))
            for row in manifest["cards"].values()
            if row.get("status") == "success"
        )
        manifest["status"] = "complete" if successful == len(cards) else "incomplete"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        _add_manifest_diagnostics(manifest, config)
        persist()
    return {**manifest, "manifest_file": _relative(manifest_path)}


def _parse_sale_observation(
    sale: dict[str, Any],
    identity: EligibleCard,
    printing: str,
    source_row_number: int,
    provider_as_of: date | None,
    source_snapshot_key: str,
    source_captured_at: datetime,
    source_name: str,
    source_file: str,
) -> ReportedSaleObservation:
    row_without_hash = ReportedSaleObservation(
        source_snapshot_key=source_snapshot_key,
        card_id=identity.card_id,
        tcgapi_card_id=identity.tcgapi_card_id,
        printing=printing,
        source_row_number=source_row_number,
        sold_date=_optional_date(sale.get("sold_date"), "sale.sold_date"),
        price=_optional_decimal(sale.get("price"), "sale.price"),
        best_offer=_optional_bool(sale.get("best_offer"), "sale.best_offer"),
        list_price=_optional_decimal(sale.get("list_price"), "sale.list_price"),
        grade_label=_optional_text(sale.get("grade"), "sale.grade"),
        condition_label=_optional_text(sale.get("condition"), "sale.condition"),
        listing_title=_optional_text(sale.get("title"), "sale.title"),
        listing_url=_optional_text(sale.get("url"), "sale.url"),
        currency_code=None,
        provider_as_of=provider_as_of,
        source_captured_at=source_captured_at,
        source_name=source_name,
        source_file=source_file,
        source_record_hash="",
    )
    return replace(
        row_without_hash,
        source_record_hash=_observation_hash(
            source_snapshot_key,
            identity.tcgapi_card_id,
            printing,
            source_row_number,
            provider_as_of,
            sale,
        ),
    )


def read_saved_reported_sales_snapshot(
    config: ReportedSaleConfig,
    cards: list[EligibleCard],
    run_directory: Path,
) -> tuple[list[ReportedSaleObservation], dict[str, Any]]:
    """Parse only a completed saved run; never call the provider."""

    manifest_path = run_directory / "request_manifest.json"
    with manifest_path.open("r", encoding="utf-8") as file:
        manifest = json.load(file)
    if manifest.get("status") != "complete":
        raise ValueError("Only a clearly completed extraction snapshot can be replayed.")
    if manifest.get("eligible_ids_hash") != _eligible_ids_hash(cards):
        raise DataIntegrityError("Saved run eligibility differs from configured scope.")
    source_snapshot_key = _required_text(
        manifest.get("source_snapshot_key"), "source_snapshot_key"
    )
    identity_map = {card.tcgapi_card_id: card for card in cards}
    rows: list[ReportedSaleObservation] = []
    missing_sales_arrays = 0
    empty_sales_arrays = 0
    price_rows_without_ebay = 0
    price_rows = 0
    cards_without_price_rows = 0
    provider_currency_fields_present = 0
    for tcgapi_card_id in sorted(identity_map):
        state = manifest["cards"].get(str(tcgapi_card_id))
        if not isinstance(state, dict) or state.get("status") != "success":
            raise DataIntegrityError(
                f"Completed snapshot lacks successful card {tcgapi_card_id}."
            )
        source_file = _required_text(state.get("raw_file"), "raw_file")
        source_path = (PROJECT_ROOT / source_file).resolve()
        if not source_path.is_relative_to(run_directory.resolve()):
            raise DataIntegrityError("Saved raw file is outside its run directory.")
        source_captured_at = _timestamp(state.get("captured_at"), "captured_at")
        with source_path.open("r", encoding="utf-8") as file:
            payload = json.load(file, parse_float=Decimal)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError(f"Card {tcgapi_card_id} saved data must be an array.")
        if not data:
            cards_without_price_rows += 1
        seen_printings: set[str] = set()
        for item in data:
            price_rows += 1
            if not isinstance(item, dict):
                raise ValueError("Every saved price row must be an object.")
            returned_id = _positive_int(item.get("card_id"), "card_id")
            if returned_id != tcgapi_card_id:
                raise DataIntegrityError("Saved card response contains a different card ID.")
            printing = _required_text(item.get("printing"), "printing")
            if printing in seen_printings:
                raise DataIntegrityError(
                    f"Card {tcgapi_card_id} repeats printing {printing!r}."
                )
            seen_printings.add(printing)
            ebay = item.get("ebay")
            if not isinstance(ebay, dict):
                price_rows_without_ebay += 1
                missing_sales_arrays += 1
                continue
            provider_as_of = _optional_date(ebay.get("as_of"), "ebay.as_of")
            sales = ebay.get("sales")
            if not isinstance(sales, list):
                missing_sales_arrays += 1
                continue
            if not sales:
                empty_sales_arrays += 1
            for source_row_number, sale in enumerate(sales, start=1):
                if not isinstance(sale, dict):
                    raise ValueError("Every saved sale observation must be an object.")
                if sale.get("currency") is not None or sale.get("currency_code") is not None:
                    provider_currency_fields_present += 1
                row = _parse_sale_observation(
                    sale,
                    identity_map[tcgapi_card_id],
                    printing,
                    source_row_number,
                    provider_as_of,
                    source_snapshot_key,
                    source_captured_at,
                    config.source_name,
                    source_file,
                )
                rows.append(row)
    replay_keys = [row.replay_key for row in rows]
    if len(set(replay_keys)) != len(replay_keys):
        raise DataIntegrityError("Parsed snapshot contains duplicate replay keys.")
    return rows, {
        "source_snapshot_key": source_snapshot_key,
        "source_run_id": manifest.get("run_id"),
        "snapshot_status": manifest.get("status"),
        "successful_card_count": len(cards),
        "price_rows": price_rows,
        "cards_without_price_rows": cards_without_price_rows,
        "price_rows_without_ebay": price_rows_without_ebay,
        "missing_sales_arrays": missing_sales_arrays,
        "empty_sales_arrays": empty_sales_arrays,
        "observation_rows": len(rows),
        "currency_code_null_rows": len(rows),
        "provider_currency_fields_present": provider_currency_fields_present,
        "source_manifest_file": _relative(manifest_path),
    }


def load_reported_sale_observations(
    rows: list[ReportedSaleObservation],
    parse_result: dict[str, Any],
) -> dict[str, Any]:
    """Insert immutable observations and reject same-key hash conflicts."""

    source_snapshot_key = _required_text(
        parse_result.get("source_snapshot_key"), "source_snapshot_key"
    )
    incoming = {row.replay_key: row for row in rows}
    if len(incoming) != len(rows):
        raise DataIntegrityError("Incoming rows contain duplicate replay keys.")
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    source_snapshot_key, card_id, printing, source_row_number,
                    source_record_hash
                FROM reported_sale_observations
                WHERE source_snapshot_key = %s;
                """,
                (source_snapshot_key,),
            )
            existing = {
                (snapshot, card_id, printing, row_number): record_hash
                for snapshot, card_id, printing, row_number, record_hash
                in cursor.fetchall()
            }
            for key, existing_hash in existing.items():
                incoming_row = incoming.get(key)
                if incoming_row is None:
                    raise DataIntegrityError(
                        "Immutable snapshot has a stored replay key absent from source."
                    )
                if incoming_row.source_record_hash != existing_hash:
                    raise DataIntegrityError(
                        "Immutable snapshot replay key has a conflicting record hash: "
                        f"{key}"
                    )

            cursor.execute(
                """
                CREATE TEMP TABLE incoming_reported_sale_observations
                ON COMMIT DROP AS
                SELECT
                    source_snapshot_key, card_id, printing, source_row_number,
                    sold_date, price, best_offer, list_price, grade_label,
                    condition_label, listing_title, listing_url, currency_code,
                    provider_as_of, source_captured_at, source_name, source_file,
                    source_record_hash
                FROM reported_sale_observations
                WITH NO DATA;
                """
            )
            with cursor.copy(
                """
                COPY incoming_reported_sale_observations (
                    source_snapshot_key, card_id, printing, source_row_number,
                    sold_date, price, best_offer, list_price, grade_label,
                    condition_label, listing_title, listing_url, currency_code,
                    provider_as_of, source_captured_at, source_name, source_file,
                    source_record_hash
                ) FROM STDIN
                """
            ) as copy:
                for row in rows:
                    copy.write_row(
                        (
                            row.source_snapshot_key,
                            row.card_id,
                            row.printing,
                            row.source_row_number,
                            row.sold_date,
                            row.price,
                            row.best_offer,
                            row.list_price,
                            row.grade_label,
                            row.condition_label,
                            row.listing_title,
                            row.listing_url,
                            row.currency_code,
                            row.provider_as_of,
                            row.source_captured_at,
                            row.source_name,
                            row.source_file,
                            row.source_record_hash,
                        )
                    )
            cursor.execute(
                """
                INSERT INTO reported_sale_observations (
                    source_snapshot_key, card_id, printing, source_row_number,
                    sold_date, price, best_offer, list_price, grade_label,
                    condition_label, listing_title, listing_url, currency_code,
                    provider_as_of, source_captured_at, source_name, source_file,
                    source_record_hash
                )
                SELECT
                    source_snapshot_key, card_id, printing, source_row_number,
                    sold_date, price, best_offer, list_price, grade_label,
                    condition_label, listing_title, listing_url, currency_code,
                    provider_as_of, source_captured_at, source_name, source_file,
                    source_record_hash
                FROM incoming_reported_sale_observations
                ON CONFLICT ON CONSTRAINT
                    uq_reported_sale_observations_replay_key
                DO NOTHING;
                """
            )
            inserted_rows = cursor.rowcount
            cursor.execute(
                """
                SELECT count(*)
                FROM reported_sale_observations
                WHERE source_snapshot_key = %s;
                """,
                (source_snapshot_key,),
            )
            database_snapshot_rows = cursor.fetchone()[0]
            if database_snapshot_rows != len(rows):
                raise DataIntegrityError(
                    "Database row count differs from immutable completed snapshot."
                )
    return {
        "inserted_rows": inserted_rows,
        "unchanged_rows": len(rows) - inserted_rows,
        "database_snapshot_rows": database_snapshot_rows,
        "conflicting_hash_rows": 0,
    }


def write_load_manifest(
    path: Path,
    run_id: str,
    parse_result: dict[str, Any],
    load_result: dict[str, Any],
) -> None:
    _write_json_atomic(
        path,
        {
            "run_id": run_id,
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            **parse_result,
            **load_result,
        },
    )
