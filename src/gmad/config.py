"""Load and validate local database configuration."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class DatabaseSettings:
    """Connection values read from the project's untracked .env file."""

    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_environment(cls) -> "DatabaseSettings":
        values = {
            "host": os.getenv("PGHOST", "localhost"),
            "port": os.getenv("PGPORT", "5432"),
            "database": os.getenv("PGDATABASE"),
            "user": os.getenv("PGUSER"),
            "password": os.getenv("PGPASSWORD"),
        }

        missing = [
            name
            for name in ("database", "user", "password")
            if not values[name] or values[name] == "replace_me"
        ]
        if missing:
            missing_names = ", ".join(f"PG{name.upper()}" for name in missing)
            raise ValueError(
                f"Missing database settings: {missing_names}. "
                "Copy .env.example to .env and replace the placeholders."
            )

        try:
            port = int(values["port"])
        except ValueError as error:
            raise ValueError("PGPORT must be an integer.") from error

        return cls(
            host=str(values["host"]),
            port=port,
            database=str(values["database"]),
            user=str(values["user"]),
            password=str(values["password"]),
        )

