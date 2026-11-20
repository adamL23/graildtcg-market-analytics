"""Task 7 entry point: snapshot and upsert cached condition prices."""

from datetime import datetime, timezone

from gmad.condition_price_ingest import (
    fetch_condition_prices,
    load_condition_price_config,
    load_condition_prices,
    select_cards,
    write_condition_price_manifest,
)
from gmad.config import PROJECT_ROOT
from gmad.tcgapi_client import TcgApiClient


def main() -> None:
    config = load_condition_price_config(
        PROJECT_ROOT / "config" / "condition_price_ingestion.json"
    )
    cards = select_cards(config)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_directory = PROJECT_ROOT / "data" / "raw" / "tcgapi_conditions" / run_id

    rows, fetch_result = fetch_condition_prices(
        TcgApiClient(timeout_seconds=60), config, cards, run_directory
    )
    load_result = load_condition_prices(config, rows, cards)
    manifest_path = run_directory / "manifest.json"
    write_condition_price_manifest(
        manifest_path, run_id, config, fetch_result, load_result
    )

    print(f"Run: {run_id}")
    print(f"Cards requested: {fetch_result['cards_requested']}")
    print(f"Cards with condition rows: {fetch_result['cards_with_condition_rows']}")
    print(
        "Cards without cached condition rows: "
        f"{fetch_result['cards_without_condition_rows']}"
    )
    print(f"Canonical condition rows: {fetch_result['canonical_rows_received']}")
    print(f"Inserted: {load_result['inserted_rows']}")
    print(f"Updated from newer snapshot: {load_result['updated_from_newer_snapshot']}")
    print(f"Same-timestamp revisions: {load_result['revised_at_same_timestamp']}")
    print(f"Unchanged: {load_result['unchanged_rows']}")
    print(f"Older provider rows skipped: {load_result['older_provider_rows_skipped']}")
    print(
        "Existing snapshots not returned (retained): "
        f"{load_result['existing_rows_not_returned']}"
    )
    print(f"Database rows: {load_result['database_rows_after_load']}")
    print(f"Manifest: {manifest_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
