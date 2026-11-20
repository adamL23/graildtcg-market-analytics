"""Task 4 entry point: snapshot and upsert configured TCGAPI set catalogs."""

from datetime import datetime, timezone

from gmad.catalog_ingest import (
    fetch_catalogs,
    load_catalogs,
    load_targets,
    write_manifest,
)
from gmad.config import PROJECT_ROOT
from gmad.tcgapi_client import TcgApiClient


def main() -> None:
    config_path = PROJECT_ROOT / "config" / "target_sets.json"
    targets, skipped_targets = load_targets(config_path)
    if not targets:
        raise SystemExit("No resolved TCGAPI targets are configured.")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_directory = PROJECT_ROOT / "data" / "raw" / "tcgapi" / run_id

    client = TcgApiClient()
    bundles = fetch_catalogs(client, targets, run_directory)
    load_result = load_catalogs(bundles)
    manifest_path = run_directory / "manifest.json"
    write_manifest(manifest_path, run_id, load_result, skipped_targets)

    print(f"Run: {run_id}")
    print(f"Sets processed: {load_result['sets_processed']}")
    print(f"Cards processed: {load_result['cards_processed']}")
    for item in load_result["sets"]:
        print(
            f"- {item['set_name']}: {item['card_rows']} cards "
            f"(TCGAPI set {item['tcgapi_set_id']})"
        )
    for item in skipped_targets:
        target_name = item.get("target_name") or item.get("set_name")
        print(f"Skipped: {target_name} ({item.get('resolution_status')})")
    print(f"Manifest: {manifest_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

