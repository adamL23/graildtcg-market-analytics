"""Task 8: fetch once or replay a saved aggregated graded-price snapshot."""

import argparse
from datetime import datetime, timezone
import re

from gmad.config import PROJECT_ROOT
from gmad.graded_price_ingest import (
    RAW_ROOT,
    fetch_graded_snapshot,
    load_graded_price_config,
    load_graded_summaries,
    read_saved_graded_snapshot,
    select_cards,
    write_load_manifest,
)
from gmad.tcgapi_client import TcgApiClient


def run_id_value(value: str) -> str:
    if not re.fullmatch(r"\d{8}T\d{12}Z", value):
        raise argparse.ArgumentTypeError("Run ID has an invalid format.")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fetch",
        action="store_true",
        help="Perform one quota-gated full bulk API request and save raw JSON only.",
    )
    mode.add_argument(
        "--replay-run",
        type=run_id_value,
        help="Load a previously saved raw run without making any API request.",
    )
    args = parser.parse_args()

    config = load_graded_price_config(
        PROJECT_ROOT / "config" / "graded_price_ingestion.json"
    )
    cards = select_cards(config)

    if args.fetch:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_directory = RAW_ROOT / run_id
        result = fetch_graded_snapshot(
            TcgApiClient(timeout_seconds=120),
            config,
            cards,
            run_directory,
            run_id,
        )
        print(f"Run: {run_id}")
        print(f"Cards requested: {result['cards_requested']}")
        print(
            "Projected cards with any eBay data: "
            f"{result['projected_cards_with_any_ebay']}"
        )
        print(f"Projected credits: {result['projected_credits']}")
        print(f"Available credits: {result['available_credits_after_probe']}")
        print(f"Actual credits consumed: {result['actual_credits_consumed']}")
        print(f"Cards with any eBay data: {result['cards_with_any_ebay']}")
        print(
            "Cards with graded summaries: "
            f"{result['cards_with_graded_summaries']}"
        )
        print(f"Raw file: {result['raw_file']}")
        print("Database load performed: no")
        return

    run_id = args.replay_run
    run_directory = RAW_ROOT / run_id
    if not run_directory.is_dir():
        raise SystemExit(f"Saved graded run does not exist: {run_id}")
    rows, parse_result, coverage_checked_at = read_saved_graded_snapshot(
        config, cards, run_directory
    )
    load_result = load_graded_summaries(
        config, rows, cards, coverage_checked_at
    )
    load_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = run_directory / f"load_manifest_{load_id}.json"
    write_load_manifest(
        manifest_path, run_id, parse_result, load_result
    )
    print(f"Source run: {run_id}")
    print(f"Cards requested: {parse_result['cards_requested']}")
    print(f"Cards with any eBay data: {parse_result['cards_with_any_ebay']}")
    print(
        "Cards with graded summaries: "
        f"{parse_result['cards_with_graded_summaries']}"
    )
    print(f"Canonical graded rows: {parse_result['canonical_graded_rows']}")
    print(f"Inserted: {load_result['inserted_rows']}")
    print(
        "Updated from newer provider date: "
        f"{load_result['updated_from_newer_provider_date']}"
    )
    print(
        "Same-date revisions: "
        f"{load_result['revised_at_same_provider_date']}"
    )
    print(f"Unchanged: {load_result['unchanged_rows']}")
    print(f"Last-known retained: {load_result['last_known_rows_after_load']}")
    print(f"Database rows: {load_result['database_rows_after_load']}")
    print(f"Load manifest: {manifest_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
