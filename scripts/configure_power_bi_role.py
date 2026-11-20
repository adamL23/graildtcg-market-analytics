"""Create and verify the dedicated read-only Power BI login once."""

import argparse
from pathlib import Path
import os
import secrets

from dotenv import dotenv_values, set_key, unset_key
import psycopg
from psycopg import sql

from gmad.config import DatabaseSettings, PROJECT_ROOT
from gmad.db import connect


REPORTING_ROLE = "graildtcg_powerbi"
REPORTING_SCHEMA = "reporting"
REPORTING_VIEWS = (
    "dim_cards",
    "fact_price_history",
    "fact_current_prices",
    "fact_condition_prices",
    "fact_graded_price_summaries",
    "fact_reported_sale_observations",
)
ENV_PATH = PROJECT_ROOT / ".env"
POWER_BI_ENV_PATH = PROJECT_ROOT / ".env.powerbi"


def admin_parameters() -> dict[str, object]:
    password = os.getenv("PGADMINPASSWORD")
    if not password or password == "replace_me":
        raise SystemExit(
            "PGADMINPASSWORD is unavailable. Add it temporarily to the ignored "
            "project .env, rerun this script, and it will be removed after success."
        )
    return {
        "host": os.getenv("PGADMINHOST", os.getenv("PGHOST", "localhost")),
        "port": int(os.getenv("PGADMINPORT", os.getenv("PGPORT", "5432"))),
        "dbname": os.getenv("PGADMINDATABASE", "postgres"),
        "user": os.getenv("PGADMINUSER", "postgres"),
        "password": password,
        "connect_timeout": 5,
    }


def reporting_password_for_new_or_existing(role_exists: bool) -> str:
    if role_exists:
        if not POWER_BI_ENV_PATH.is_file():
            raise SystemExit(
                f"Role {REPORTING_ROLE!r} already exists but .env.powerbi is missing. "
                "Refusing to rotate an unknown credential automatically."
            )
        values = dotenv_values(POWER_BI_ENV_PATH)
        password = values.get("PGPASSWORD")
        if not password:
            raise SystemExit(".env.powerbi does not contain PGPASSWORD.")
        return str(password)
    return secrets.token_urlsafe(32)


def save_reporting_environment(settings: DatabaseSettings, password: str) -> None:
    values = {
        "PGHOST": settings.host,
        "PGPORT": str(settings.port),
        "PGDATABASE": settings.database,
        "PGUSER": REPORTING_ROLE,
        "PGPASSWORD": password,
    }
    for key, value in values.items():
        set_key(POWER_BI_ENV_PATH, key, value, quote_mode="always")


def create_login(admin: dict[str, object], password: str) -> bool:
    created = False
    with psycopg.connect(**admin, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            )
            row = cursor.fetchone()
            if row is None or not row[0]:
                raise SystemExit("Power BI role setup requires PostgreSQL superuser access.")
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (REPORTING_ROLE,)
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5"
                    ).format(
                        sql.Identifier(REPORTING_ROLE), sql.Literal(password)
                    )
                )
                created = True
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path = reporting, pg_catalog").format(
                    sql.Identifier(REPORTING_ROLE)
                )
            )
    return created


def grant_view_only_access(settings: DatabaseSettings) -> None:
    role = sql.Identifier(REPORTING_ROLE)
    schema = sql.Identifier(REPORTING_SCHEMA)
    database = sql.Identifier(settings.database)
    view_list = sql.SQL(", ").join(
        sql.SQL("{}.{}").format(schema, sql.Identifier(view))
        for view in REPORTING_VIEWS
    )
    with connect(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
            cursor.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(role))
            cursor.execute(
                sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role)
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role)
            )
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role))
            cursor.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(view_list, role))


def verify_reporting_login(settings: DatabaseSettings, password: str) -> list[tuple[str, int]]:
    parameters = {
        "host": settings.host,
        "port": settings.port,
        "dbname": settings.database,
        "user": REPORTING_ROLE,
        "password": password,
        "connect_timeout": 5,
    }
    counts: list[tuple[str, int]] = []
    with psycopg.connect(**parameters) as connection:
        with connection.cursor() as cursor:
            for view in REPORTING_VIEWS:
                cursor.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(REPORTING_SCHEMA), sql.Identifier(view)
                    )
                )
                counts.append((view, cursor.fetchone()[0]))
            cursor.execute(
                """
                SELECT table_name, has_table_privilege(
                    current_user, format('public.%I', table_name), 'SELECT'
                )
                FROM (VALUES
                    ('sets'), ('cards'), ('price_history'), ('current_prices'),
                    ('condition_prices'), ('graded_price_summaries'),
                    ('reported_sale_observations')
                ) AS operational(table_name)
                ORDER BY table_name;
                """
            )
            direct_privileges = cursor.fetchall()
            if any(has_select for _, has_select in direct_privileges):
                raise RuntimeError(
                    f"Reporting role has unexpected operational SELECT: {direct_privileges}"
                )
            try:
                cursor.execute("SELECT count(*) FROM public.cards")
            except psycopg.errors.InsufficientPrivilege:
                connection.rollback()
            else:
                raise RuntimeError("Reporting role unexpectedly queried public.cards.")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify the saved read-only login without administrator access.",
    )
    args = parser.parse_args()
    settings = DatabaseSettings.from_environment()
    if args.verify_only:
        values = dotenv_values(POWER_BI_ENV_PATH)
        password = values.get("PGPASSWORD")
        if not password:
            raise SystemExit(".env.powerbi does not contain PGPASSWORD.")
        counts = verify_reporting_login(settings, str(password))
        print(f"Reporting role: {REPORTING_ROLE}")
        print("Operational table SELECT privileges: none")
        for view, count in counts:
            print(f"reporting.{view}: {count}")
        return
    admin = admin_parameters()
    with psycopg.connect(**admin) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (REPORTING_ROLE,)
            )
            role_exists = cursor.fetchone() is not None
    password = reporting_password_for_new_or_existing(role_exists)
    created = create_login(admin, password)
    grant_view_only_access(settings)
    save_reporting_environment(settings, password)
    counts = verify_reporting_login(settings, password)
    unset_key(ENV_PATH, "PGADMINPASSWORD")

    print(f"Reporting role: {REPORTING_ROLE}")
    print(f"Role created: {created}")
    print("Operational table SELECT privileges: none")
    for view, count in counts:
        print(f"reporting.{view}: {count}")
    print("Saved local Power BI connection values to ignored .env.powerbi.")
    print("Removed PGADMINPASSWORD from the project .env.")


if __name__ == "__main__":
    main()
