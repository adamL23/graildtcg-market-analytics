"""Resolve, validate, snapshot, and load configured TCGAPI.dev catalogs."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from gmad.config import PROJECT_ROOT
from gmad.db import connect
from gmad.tcgapi_client import TcgApiClient


SOURCE_NAME = "tcgapi.dev"


@dataclass(frozen=True)
class TargetSet:
    source_set_key: str
    tcgapi_set_id: int
    game_id: int
    game_name: str
    game_slug: str
    language_code: str
    region_code: str | None
    provider_set_name: str
    expected_card_rows: int
    catalog_references: tuple[str, ...]


@dataclass(frozen=True)
class CardSnapshot:
    payload: dict[str, Any]
    source_file: str
    observed_at: datetime


@dataclass(frozen=True)
class CatalogBundle:
    target: TargetSet
    set_payload: dict[str, Any]
    set_source_file: str
    set_observed_at: datetime
    cards: tuple[CardSnapshot, ...]


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string.")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer.")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Optional text value must be a string or null.")
    return value.strip() or None


def _parse_timestamp(value: Any, fallback: datetime) -> datetime:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("release_date must be an ISO date string or null.")
    return date.fromisoformat(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def _project_relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def load_targets(config_path: Path) -> tuple[list[TargetSet], list[dict[str, Any]]]:
    """Load resolved targets and deduplicate regional references canonically."""

    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    items = config.get("targets")
    if not isinstance(items, list):
        raise ValueError("Target configuration must contain a targets array.")

    grouped: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Every target entry must be an object.")
        if item.get("resolution_status") != "resolved_tcgapi":
            skipped.append(item)
            continue

        source_set_key = _required_text(
            item.get("canonical_source_set_key"), "canonical_source_set_key"
        )
        comparable = (
            item.get("tcgapi_set_id"),
            item.get("game_id"),
            item.get("game_name"),
            item.get("game_slug"),
            item.get("language_code"),
            item.get("region_code"),
            item.get("provider_set_name"),
            item.get("expected_card_rows"),
        )
        existing = grouped.get(source_set_key)
        if existing is None:
            grouped[source_set_key] = {
                "item": item,
                "comparable": comparable,
                "references": [],
            }
            existing = grouped[source_set_key]
        elif existing["comparable"] != comparable:
            raise ValueError(
                f"Conflicting target definitions for {source_set_key}."
            )

        reference = item.get("catalog_reference")
        if isinstance(reference, str) and reference.strip():
            existing["references"].append(reference.strip())

    targets: list[TargetSet] = []
    for source_set_key, grouped_item in grouped.items():
        item = grouped_item["item"]
        targets.append(
            TargetSet(
                source_set_key=source_set_key,
                tcgapi_set_id=_positive_int(
                    item.get("tcgapi_set_id"), "tcgapi_set_id"
                ),
                game_id=_positive_int(item.get("game_id"), "game_id"),
                game_name=_required_text(item.get("game_name"), "game_name"),
                game_slug=_required_text(item.get("game_slug"), "game_slug"),
                language_code=_required_text(
                    item.get("language_code"), "language_code"
                ),
                region_code=_optional_text(item.get("region_code")),
                provider_set_name=_required_text(
                    item.get("provider_set_name"), "provider_set_name"
                ),
                expected_card_rows=_positive_int(
                    item.get("expected_card_rows"), "expected_card_rows"
                ),
                catalog_references=tuple(sorted(set(grouped_item["references"]))),
            )
        )

    return sorted(targets, key=lambda target: target.tcgapi_set_id), skipped


def fetch_catalogs(
    client: TcgApiClient, targets: list[TargetSet], run_directory: Path
) -> list[CatalogBundle]:
    """Fetch all targets completely before opening a database transaction."""

    bundles: list[CatalogBundle] = []
    observed_card_ids: dict[int, str] = {}
    for target in targets:
        observed_at = datetime.now(timezone.utc)
        set_response = client.get_set(target.tcgapi_set_id)
        set_path = run_directory / str(target.tcgapi_set_id) / "set.json"
        _write_json(set_path, set_response)

        set_payload = set_response.get("data")
        if not isinstance(set_payload, dict):
            raise ValueError(f"Set {target.tcgapi_set_id} response has no data object.")
        if _positive_int(set_payload.get("id"), "set.id") != target.tcgapi_set_id:
            raise ValueError(f"Set ID mismatch for {target.source_set_key}.")
        if _positive_int(set_payload.get("game_id"), "set.game_id") != target.game_id:
            raise ValueError(f"Game ID mismatch for {target.source_set_key}.")
        if _required_text(set_payload.get("name"), "set.name") != target.provider_set_name:
            raise ValueError(f"Set name mismatch for {target.source_set_key}.")
        if _required_text(set_payload.get("game_name"), "set.game_name") != target.game_name:
            raise ValueError(f"Game name mismatch for {target.source_set_key}.")

        card_snapshots: list[CardSnapshot] = []
        reported_total: int | None = None
        for page, page_response in client.iter_set_card_pages(target.tcgapi_set_id):
            page_path = (
                run_directory
                / str(target.tcgapi_set_id)
                / f"cards_page_{page:03d}.json"
            )
            _write_json(page_path, page_response)

            data = page_response.get("data")
            meta = page_response.get("meta")
            if not isinstance(data, list) or not isinstance(meta, dict):
                raise ValueError(
                    f"Malformed card page {page} for set {target.tcgapi_set_id}."
                )
            total = _positive_int(meta.get("total"), "cards.meta.total")
            if reported_total is None:
                reported_total = total
            elif reported_total != total:
                raise ValueError(
                    f"Provider total changed during pagination for set {target.tcgapi_set_id}."
                )

            for card in data:
                if not isinstance(card, dict):
                    raise ValueError("Every card response item must be an object.")
                card_id = _positive_int(card.get("id"), "card.id")
                existing_set_key = observed_card_ids.get(card_id)
                if existing_set_key and existing_set_key != target.source_set_key:
                    raise ValueError(
                        f"Card {card_id} appeared in two configured canonical sets."
                    )
                if existing_set_key:
                    raise ValueError(
                        f"Card {card_id} appeared more than once in {target.source_set_key}."
                    )
                observed_card_ids[card_id] = target.source_set_key
                card_snapshots.append(
                    CardSnapshot(
                        payload=card,
                        source_file=_project_relative(page_path),
                        observed_at=observed_at,
                    )
                )

        if reported_total != target.expected_card_rows:
            raise ValueError(
                f"Expected {target.expected_card_rows} cards for {target.provider_set_name}, "
                f"provider reported {reported_total}."
            )
        if len(card_snapshots) != reported_total:
            raise ValueError(
                f"Fetched {len(card_snapshots)} of {reported_total} cards for "
                f"{target.provider_set_name}."
            )

        bundles.append(
            CatalogBundle(
                target=target,
                set_payload=set_payload,
                set_source_file=_project_relative(set_path),
                set_observed_at=_parse_timestamp(
                    set_payload.get("last_synced_at"), observed_at
                ),
                cards=tuple(card_snapshots),
            )
        )

    return bundles


def load_catalogs(bundles: list[CatalogBundle]) -> dict[str, Any]:
    """Upsert all validated set/card rows in one transaction."""

    set_results: list[dict[str, Any]] = []
    with connect() as connection:
        with connection.cursor() as cursor:
            for bundle in bundles:
                target = bundle.target
                set_payload = bundle.set_payload
                cursor.execute(
                    """
                    INSERT INTO sets (
                        tcgapi_set_id, source_set_key, game_id, game_name,
                        set_name, set_code, language_code, region_code,
                        release_date, source_name, source_observed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_name, source_set_key)
                    DO UPDATE SET
                        tcgapi_set_id = EXCLUDED.tcgapi_set_id,
                        game_id = EXCLUDED.game_id,
                        game_name = EXCLUDED.game_name,
                        set_name = EXCLUDED.set_name,
                        set_code = EXCLUDED.set_code,
                        language_code = EXCLUDED.language_code,
                        region_code = EXCLUDED.region_code,
                        release_date = EXCLUDED.release_date,
                        source_observed_at = EXCLUDED.source_observed_at,
                        loaded_at = CURRENT_TIMESTAMP
                    RETURNING set_id;
                    """,
                    (
                        target.tcgapi_set_id,
                        target.source_set_key,
                        target.game_id,
                        target.game_name,
                        target.provider_set_name,
                        _optional_text(set_payload.get("abbreviation")),
                        target.language_code,
                        target.region_code,
                        _parse_date(set_payload.get("release_date")),
                        SOURCE_NAME,
                        bundle.set_observed_at,
                    ),
                )
                internal_set_id = cursor.fetchone()[0]

                for snapshot in bundle.cards:
                    card = snapshot.payload
                    product_type = _required_text(
                        card.get("product_type"), "card.product_type"
                    )
                    if product_type != "Cards":
                        raise ValueError(
                            f"Unexpected product_type {product_type!r} in card-only catalog."
                        )

                    tcgplayer_id = card.get("tcgplayer_id")
                    if tcgplayer_id is not None:
                        tcgplayer_id = _positive_int(
                            tcgplayer_id, "card.tcgplayer_id"
                        )

                    cursor.execute(
                        """
                        INSERT INTO cards (
                            tcgapi_card_id, tcgplayer_id, card_name, card_number,
                            rarity, variant_name, image_url, source_file,
                            source_observed_at, source_name, set_id
                        )
                        VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s)
                        ON CONFLICT (tcgapi_card_id)
                        DO UPDATE SET
                            tcgplayer_id = EXCLUDED.tcgplayer_id,
                            card_name = EXCLUDED.card_name,
                            card_number = EXCLUDED.card_number,
                            rarity = EXCLUDED.rarity,
                            image_url = EXCLUDED.image_url,
                            source_file = EXCLUDED.source_file,
                            source_observed_at = EXCLUDED.source_observed_at,
                            source_name = EXCLUDED.source_name,
                            set_id = EXCLUDED.set_id,
                            loaded_at = CURRENT_TIMESTAMP;
                        """,
                        (
                            _positive_int(card.get("id"), "card.id"),
                            tcgplayer_id,
                            _required_text(card.get("name"), "card.name"),
                            _optional_text(card.get("number")),
                            _optional_text(card.get("rarity")),
                            _optional_text(card.get("image_url")),
                            snapshot.source_file,
                            snapshot.observed_at,
                            SOURCE_NAME,
                            internal_set_id,
                        ),
                    )

                cursor.execute(
                    "SELECT count(*) FROM cards WHERE set_id = %s",
                    (internal_set_id,),
                )
                database_card_count = cursor.fetchone()[0]
                if database_card_count != len(bundle.cards):
                    raise ValueError(
                        f"Database count mismatch for {target.provider_set_name}: "
                        f"expected {len(bundle.cards)}, found {database_card_count}."
                    )

                set_results.append(
                    {
                        "set_id": internal_set_id,
                        "tcgapi_set_id": target.tcgapi_set_id,
                        "set_name": target.provider_set_name,
                        "card_rows": database_card_count,
                        "catalog_references": list(target.catalog_references),
                        "raw_set_file": bundle.set_source_file,
                    }
                )

    return {
        "sets_processed": len(set_results),
        "cards_processed": sum(item["card_rows"] for item in set_results),
        "sets": set_results,
    }


def write_manifest(
    path: Path,
    run_id: str,
    load_result: dict[str, Any],
    skipped_targets: list[dict[str, Any]],
) -> None:
    manifest = {
        "run_id": run_id,
        "source_name": SOURCE_NAME,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        **load_result,
        "skipped_targets": [
            {
                "target_name": item.get("target_name") or item.get("set_name"),
                "catalog_reference": item.get("catalog_reference"),
                "resolution_status": item.get("resolution_status"),
            }
            for item in skipped_targets
        ],
    }
    _write_json(path, manifest)

