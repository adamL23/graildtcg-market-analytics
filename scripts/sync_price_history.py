"""Task 5 entry point: snapshot and upsert bulk TCGAPI price history."""

from datetime import datetime, timezone

from gmad.config import PROJECT_ROOT
from gmad.history_ingest import (
    fetch_history,
    load_history,
    load_history_config,
    select_cards,
    write_history_manifest,
)
from gmad.tcgapi_client import TcgApiClient


def main() -> None:
    config = load_history_config(
        PROJECT_ROOT / "config" / "history_ingestion.json"
    )
    cards = select_cards(config)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_directory = PROJECT_ROOT / "data" / "raw" / "tcgapi_history" / run_id

    rows, fetch_result = fetch_history(
        TcgApiClient(), config, cards, run_directory
    )
    load_result = load_history(config, rows, cards)
    manifest_path = run_directory / "manifest.json"
    write_history_manifest(
        manifest_path, run_id, config, fetch_result, load_result
    )

    print(f"Run: {run_id}")
    print(f"Cards requested: {fetch_result['requested_cards']}")
    print(f"Cards with history: {fetch_result['cards_with_history']}")
    print(f"Cards without history: {fetch_result['cards_without_history']}")
    print(
        "Provider-omitted card keys: "
        f"{fetch_result['provider_omitted_card_count']}"
    )
    print(f"Canonical observations: {fetch_result['canonical_rows_received']}")
    print(f"Inserted: {load_result['inserted_rows']}")
    print(f"Revised: {load_result['revised_rows']}")
    print(f"Unchanged: {load_result['unchanged_rows']}")
    print(
        "Existing observations not returned (retained): "
        f"{load_result['existing_rows_not_returned']}"
    )
    print(f"Database rows: {load_result['database_rows_after_load']}")
    print(f"Manifest: {manifest_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

