"""Task 9: controlled fetch/resume and offline replay of sale observations."""

import argparse
from datetime import datetime, timezone
import re

from gmad.config import PROJECT_ROOT
from gmad.reported_sale_ingest import (
    RAW_ROOT,
    fetch_reported_sales_snapshot,
    load_reported_sale_config,
    load_reported_sale_observations,
    read_saved_reported_sales_snapshot,
    select_eligible_cards,
    write_load_manifest,
)


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
        help="Start a new quota- and hard-ceiling-gated 481-card extraction.",
    )
    mode.add_argument(
        "--resume-run",
        type=run_id_value,
        help="Resume an incomplete extraction without repeating successful cards.",
    )
    mode.add_argument(
        "--replay-run",
        type=run_id_value,
        help="Load a completed saved extraction without making API requests.",
    )
    args = parser.parse_args()

    config = load_reported_sale_config(
        PROJECT_ROOT / "config" / "reported_sale_ingestion.json"
    )
    cards, eligibility = select_eligible_cards(config)

    if args.fetch or args.resume_run:
        run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            if args.fetch
            else args.resume_run
        )
        result = fetch_reported_sales_snapshot(
            config,
            cards,
            eligibility,
            RAW_ROOT / run_id,
            run_id,
            resume=bool(args.resume_run),
        )
        print(f"Run: {run_id}")
        print(f"Snapshot key: {result['source_snapshot_key']}")
        print(f"Status: {result['status']}")
        print(f"Eligible cards: {result['eligible_card_count']}")
        print(f"Successful responses: {result['successful_card_count']}")
        print(f"Failed cards: {result['failed_card_count']}")
        print(f"Baseline card credits: {result['baseline_projected_card_credits']}")
        print(
            "Reserved attempt credits including probes: "
            f"{result['estimated_credits_reserved_including_probes']}"
        )
        print(f"Reported successful-card credits: {result['reported_card_credits']}")
        print(f"Manifest: {result['manifest_file']}")
        print("Database load performed: no")
        return

    run_id = args.replay_run
    run_directory = RAW_ROOT / run_id
    if not run_directory.is_dir():
        raise SystemExit(f"Saved reported-sales run does not exist: {run_id}")
    rows, parse_result = read_saved_reported_sales_snapshot(
        config, cards, run_directory
    )
    load_result = load_reported_sale_observations(rows, parse_result)
    load_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = run_directory / f"load_manifest_{load_id}.json"
    write_load_manifest(manifest_path, run_id, parse_result, load_result)
    print(f"Source run: {run_id}")
    print(f"Snapshot key: {parse_result['source_snapshot_key']}")
    print(f"Successful card responses: {parse_result['successful_card_count']}")
    print(f"Observation rows: {parse_result['observation_rows']}")
    print(f"Inserted: {load_result['inserted_rows']}")
    print(f"Unchanged: {load_result['unchanged_rows']}")
    print(f"Database snapshot rows: {load_result['database_snapshot_rows']}")
    print(f"Load manifest: {manifest_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
