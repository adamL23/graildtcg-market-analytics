"""Task 6 entry point: snapshot and upsert latest TCGAPI current prices."""

from datetime import datetime, timezone

from gmad.config import PROJECT_ROOT
from gmad.current_price_ingest import (
    fetch_current_prices,
    load_current_price_config,
    load_current_prices,
    select_catalog,
    write_current_price_manifest,
)
from gmad.tcgapi_client import TcgApiClient


def main() -> None:
    config = load_current_price_config(
        PROJECT_ROOT / "config" / "current_price_ingestion.json"
    )
    catalogs = select_catalog(config)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_directory = PROJECT_ROOT / "data" / "raw" / "tcgapi_current" / run_id

    rows, fetch_result = fetch_current_prices(
        TcgApiClient(), config, catalogs, run_directory
    )
    load_result = load_current_prices(config, rows, catalogs)
    manifest_path = run_directory / "manifest.json"
    write_current_price_manifest(
        manifest_path, run_id, config, fetch_result, load_result
    )

    print(f"Run: {run_id}")
    print(f"Sets requested: {fetch_result['sets_requested']}")
    print(f"Cards requested: {fetch_result['cards_requested']}")
    print(f"Canonical snapshots: {fetch_result['canonical_rows_received']}")
    print(f"Market-price NULLs: {fetch_result['market_price_nulls']}")
    print(f"Market-price zero flags: {fetch_result['market_price_zeroes']}")
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
