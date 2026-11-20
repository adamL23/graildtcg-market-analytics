"""Small PostgreSQL connection boundary for the project."""

import psycopg
from psycopg import Connection

from gmad.config import DatabaseSettings


def connect(settings: DatabaseSettings | None = None) -> Connection:
    """Open a database connection without logging credentials."""

    settings = settings or DatabaseSettings.from_environment()
    return psycopg.connect(
        host=settings.host,
        port=settings.port,
        dbname=settings.database,
        user=settings.user,
        password=settings.password,
        connect_timeout=5,
    )

