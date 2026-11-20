"""Run the Phase 1 database connection smoke test."""

import psycopg

from gmad.db import connect


SMOKE_TEST_QUERY = """
SELECT
    version() AS server_version,
    current_database() AS database_name,
    current_user AS user_name,
    1 AS connection_check;
"""


def main() -> None:
    """Connect, run read-only checks, and print non-sensitive results."""

    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(SMOKE_TEST_QUERY)
                server_version, database_name, user_name, connection_check = cursor.fetchone()
    except ValueError as error:
        raise SystemExit(f"Configuration error: {error}") from error
    except psycopg.OperationalError as error:
        raise SystemExit(f"Database connection failed: {error}") from error

    print(f"Server: {server_version}")
    print(f"Database: {database_name}")
    print(f"User: {user_name}")
    print(f"SELECT 1: {connection_check}")


if __name__ == "__main__":
    main()

