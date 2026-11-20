"""Apply or inspect a project SQL file through the configured database login."""

import argparse
from pathlib import Path

from gmad.config import PROJECT_ROOT
from gmad.db import connect


SQL_DIRECTORY = (PROJECT_ROOT / "sql").resolve()


def sql_path(value: str) -> Path:
    """Allow only .sql files stored inside the project's sql directory."""

    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()

    if path.suffix.lower() != ".sql" or not path.is_relative_to(SQL_DIRECTORY):
        raise argparse.ArgumentTypeError(
            f"SQL file must be a .sql file inside {SQL_DIRECTORY}"
        )
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"SQL file does not exist: {path}")
    return path


def print_current_result(cursor, result_number: int) -> None:
    """Print a SELECT result without special formatting dependencies."""

    if cursor.description is None:
        return

    headers = [column.name for column in cursor.description]
    rows = cursor.fetchall()
    print(f"Result {result_number}: {len(rows)} row(s)")
    print(" | ".join(headers))
    for row in rows:
        print(" | ".join("NULL" if value is None else str(value) for value in row))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sql_file", type=sql_path)
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Ask PostgreSQL to reject any data or schema changes.",
    )
    args = parser.parse_args()

    statement = args.sql_file.read_text(encoding="utf-8")
    with connect() as connection:
        if args.read_only:
            connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute(statement)
            result_number = 1
            while True:
                print_current_result(cursor, result_number)
                if not cursor.nextset():
                    break
                result_number += 1

    if args.read_only:
        action = "Verified"
    elif args.sql_file.name.startswith("test_"):
        action = "Tested"
    else:
        action = "Applied"
    print(f"{action}: {args.sql_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

