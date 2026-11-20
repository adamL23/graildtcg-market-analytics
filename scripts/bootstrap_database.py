"""Create the dedicated Phase 1 database and restricted login role once."""

from pathlib import Path
import secrets

from dotenv import set_key
import psycopg
from psycopg import sql

from gmad.config import DatabaseSettings, PROJECT_ROOT


APP_DATABASE = "graildtcg"
APP_ROLE = "graildtcg_app"
ENV_PATH = PROJECT_ROOT / ".env"


def connection_parameters(settings: DatabaseSettings) -> dict[str, object]:
    """Convert validated settings into Psycopg keyword arguments."""

    return {
        "host": settings.host,
        "port": settings.port,
        "dbname": settings.database,
        "user": settings.user,
        "password": settings.password,
        "connect_timeout": 5,
    }


def names_are_available(cursor: psycopg.Cursor) -> bool:
    """Refuse to alter pre-existing objects with the requested names."""

    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
    role_exists = cursor.fetchone() is not None

    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (APP_DATABASE,))
    database_exists = cursor.fetchone() is not None

    if role_exists or database_exists:
        occupied = []
        if role_exists:
            occupied.append(f"role {APP_ROLE!r}")
        if database_exists:
            occupied.append(f"database {APP_DATABASE!r}")
        print("No changes made: " + " and ".join(occupied) + " already exists.")
        return False

    return True


def update_application_environment(password: str) -> None:
    """Switch the ignored local environment to the restricted application login."""

    values = {
        "PGHOST": "localhost",
        "PGPORT": "5432",
        "PGDATABASE": APP_DATABASE,
        "PGUSER": APP_ROLE,
        "PGPASSWORD": password,
    }
    for key, value in values.items():
        set_key(ENV_PATH, key, value, quote_mode="always")


def main() -> None:
    """Create, verify, and configure the dedicated database and role."""

    admin_settings = DatabaseSettings.from_environment()
    app_password = secrets.token_urlsafe(32)
    admin_parameters = connection_parameters(admin_settings)

    with psycopg.connect(**admin_parameters, autocommit=True) as admin_connection:
        with admin_connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            )
            result = cursor.fetchone()
            if result is None or not result[0]:
                raise SystemExit(
                    "Bootstrap requires the existing PostgreSQL superuser connection."
                )

            if not names_are_available(cursor):
                raise SystemExit(1)

            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
                ).format(sql.Identifier(APP_ROLE), sql.Literal(app_password))
            )
            cursor.execute(
                sql.SQL(
                    "CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0"
                ).format(sql.Identifier(APP_DATABASE), sql.Identifier(APP_ROLE))
            )

    app_parameters = {
        "host": "localhost",
        "port": 5432,
        "dbname": APP_DATABASE,
        "user": APP_ROLE,
        "password": app_password,
        "connect_timeout": 5,
    }
    with psycopg.connect(**app_parameters) as app_connection:
        with app_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database(),
                    current_user,
                    rolsuper,
                    rolcreatedb,
                    rolcreaterole,
                    rolreplication
                FROM pg_roles
                WHERE rolname = current_user;
                """
            )
            verification = cursor.fetchone()

    update_application_environment(app_password)

    database_name, user_name, *privileged_attributes = verification
    print(f"Created database: {database_name}")
    print(f"Created login role: {user_name}")
    print(f"Privileged role attributes: {privileged_attributes}")
    print("Updated .env with the generated application credential.")
    print("The generated password was not displayed.")


if __name__ == "__main__":
    main()

