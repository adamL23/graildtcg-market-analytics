# Chapter 13 — Build Your Own Mini Pipeline

This standalone exercise uses local JSON only: it makes no API request and
spends no credits. It demonstrates immutable raw evidence, validation,
`Decimal`, hashing, `COPY`, a timestamp guard, transaction rollback, and a true
idempotent no-op. The code is a **teaching example**, not GraildTCG production
code.

## What you need

- Python 3.11 or later available as `py`.
- PostgreSQL 15 or later installed locally. The `psql` command-line tool should
  be on `PATH`; on Windows it is normally under
  `C:\Program Files\PostgreSQL\<version>\bin`.
- A local PostgreSQL login allowed to create a practice database. The examples
  use the administrative login name `postgres`; change only the `-U` value if
  your local administrator has a different name.
- The password chosen during PostgreSQL installation. Commands using `psql`
  will prompt for it; do not put it in shell history.

If `psql --version` fails, add PostgreSQL's `bin` directory to `PATH` or use its
full path. If authentication fails, confirm host, port, user, and password in
pgAdmin before continuing.

## 1. Create the exact folder structure

```text
graildtcg-mini-pipeline/
├── .env
├── .env.example
├── .gitignore
├── fixture/
│   ├── base.json
│   ├── newer.json
│   ├── older.json
│   └── malformed.json
├── raw/                       # created by the loader
├── load_fixture.py
├── requirements.txt
├── schema.sql
└── verify.sql
```

Create and enter the folder:

```powershell
New-Item -ItemType Directory graildtcg-mini-pipeline
Set-Location graildtcg-mini-pipeline
New-Item -ItemType Directory fixture
```

Save the following files exactly.

### `requirements.txt`

```text
psycopg[binary]>=3.3,<4
python-dotenv>=1.1,<2
```

### `.gitignore`

```text
.env
.venv/
raw/
__pycache__/
```

### `.env.example`

```dotenv
PGHOST=localhost
PGPORT=5432
PGDATABASE=learning_prices
PGUSER=postgres
PGPASSWORD=replace_me
```

Copy it to `.env` and replace only `replace_me` with your local password. Keep
`.env` untracked.

### `fixture/base.json`

```json
{
  "captured_at": "2026-01-01T00:00:00Z",
  "cards": [
    {"provider_id": 101, "name": "Practice Dragon", "market_price": 12.34}
  ]
}
```

### `fixture/newer.json`

```json
{
  "captured_at": "2026-01-02T00:00:00Z",
  "cards": [
    {"provider_id": 101, "name": "Practice Dragon", "market_price": 13.00}
  ]
}
```

### `fixture/older.json`

```json
{
  "captured_at": "2025-12-31T00:00:00Z",
  "cards": [
    {"provider_id": 101, "name": "Practice Dragon", "market_price": 999.00}
  ]
}
```

### `fixture/malformed.json`

```json
{
  "captured_at": "2026-01-03T00:00:00Z",
  "cards": {"provider_id": 101, "market_price": -1}
}
```

The last file is syntactically valid JSON but violates the response contract:
`cards` must be an array. The loader will preserve it as evidence, reject it,
and never open a database transaction.

## 2. Create the schema

Save as `schema.sql`:

```sql
CREATE TABLE practice_cards (
    card_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id BIGINT NOT NULL UNIQUE CHECK (provider_id > 0),
    card_name TEXT NOT NULL CHECK (btrim(card_name) <> '')
);

CREATE TABLE practice_current_prices (
    card_id BIGINT PRIMARY KEY
        REFERENCES practice_cards(card_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    market_price NUMERIC(12,2),
    provider_observed_at TIMESTAMPTZ NOT NULL,
    source_file TEXT NOT NULL CHECK (btrim(source_file) <> ''),
    source_hash CHAR(64) NOT NULL
        CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (market_price IS NULL OR market_price >= 0)
);

CREATE VIEW practice_reporting AS
SELECT c.card_id, c.provider_id, c.card_name,
       p.market_price, p.provider_observed_at,
       p.source_file, p.source_hash, p.loaded_at
FROM practice_cards AS c
JOIN practice_current_prices AS p USING (card_id);
```

The current-price grain is one row per practice card. The provider timestamp
orders competing snapshots; `loaded_at` records database ingestion and must not
be used to decide which provider observation wins.

## 3. Create the loader

Save as `load_fixture.py`:

```python
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path

from dotenv import load_dotenv
import psycopg


RAW_DIRECTORY = Path("raw")


@dataclass(frozen=True)
class PriceRow:
    provider_id: int
    card_name: str
    market_price: Decimal | None
    provider_observed_at: datetime
    source_file: str
    source_hash: str


def required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonblank text")
    return value.strip()


def positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def optional_price(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("market_price must be numeric or null")
    try:
        price = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("market_price must be numeric or null") from error
    if not price.is_finite() or price < 0:
        raise ValueError("market_price must be finite and nonnegative")
    return price


def timestamp(value: object) -> datetime:
    text = required_text(value, "captured_at")
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("captured_at must be a valid ISO timestamp") from error
    if result.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return result


def preserve_raw(source: Path) -> tuple[bytes, Path]:
    raw_bytes = source.read_bytes()
    body_hash = sha256(raw_bytes).hexdigest()
    RAW_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = RAW_DIRECTORY / f"snapshot_{body_hash}.json"
    if destination.exists():
        if destination.read_bytes() != raw_bytes:
            raise RuntimeError("immutable raw snapshot hash collision")
    else:
        destination.write_bytes(raw_bytes)
    return raw_bytes, destination


def record_hash(
    provider_id: int,
    market_price: Decimal | None,
    observed_at: datetime,
) -> str:
    normalized = {
        "market_price": None if market_price is None else format(market_price, "f"),
        "provider_id": provider_id,
        "provider_observed_at": observed_at.isoformat(),
    }
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def parse_fixture(source: Path) -> list[PriceRow]:
    raw_bytes, raw_path = preserve_raw(source)  # evidence exists even if invalid
    payload = json.loads(raw_bytes.decode("utf-8"), parse_float=Decimal)
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")
    observed_at = timestamp(payload.get("captured_at"))
    cards = payload.get("cards")
    if not isinstance(cards, list):
        raise ValueError("cards must be an array")

    rows: list[PriceRow] = []
    seen: set[int] = set()
    for position, item in enumerate(cards, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"cards[{position}] must be an object")
        provider_id = positive_int(item.get("provider_id"), "provider_id")
        if provider_id in seen:
            raise ValueError(f"duplicate provider_id {provider_id}")
        seen.add(provider_id)
        name = required_text(item.get("name"), "name")
        price = optional_price(item.get("market_price"))
        rows.append(
            PriceRow(
                provider_id=provider_id,
                card_name=name,
                market_price=price,
                provider_observed_at=observed_at,
                source_file=raw_path.as_posix(),
                source_hash=record_hash(provider_id, price, observed_at),
            )
        )
    if not rows:
        raise ValueError("cards must not be empty")
    return rows


def load_rows(rows: list[PriceRow]) -> dict[str, int]:
    counts = {
        "inserted": 0,
        "updated_newer": 0,
        "revised_same_timestamp": 0,
        "unchanged": 0,
        "older_skipped": 0,
    }
    with psycopg.connect() as connection:
        with connection.cursor() as cursor:
            provider_ids = [row.provider_id for row in rows]
            cursor.execute(
                """
                SELECT c.provider_id, p.provider_observed_at, p.source_hash
                FROM practice_cards AS c
                JOIN practice_current_prices AS p USING (card_id)
                WHERE c.provider_id = ANY(%s)
                """,
                (provider_ids,),
            )
            existing = {
                provider_id: (observed_at, source_hash)
                for provider_id, observed_at, source_hash in cursor.fetchall()
            }
            for row in rows:
                prior = existing.get(row.provider_id)
                if prior is None:
                    counts["inserted"] += 1
                elif row.provider_observed_at < prior[0]:
                    counts["older_skipped"] += 1
                elif row.provider_observed_at > prior[0]:
                    counts["updated_newer"] += 1
                elif row.source_hash == prior[1]:
                    counts["unchanged"] += 1
                else:
                    counts["revised_same_timestamp"] += 1

            cursor.execute(
                """
                CREATE TEMP TABLE incoming_prices (
                    provider_id BIGINT,
                    card_name TEXT,
                    market_price NUMERIC(12,2),
                    provider_observed_at TIMESTAMPTZ,
                    source_file TEXT,
                    source_hash CHAR(64)
                ) ON COMMIT DROP
                """
            )
            with cursor.copy(
                """
                COPY incoming_prices (
                    provider_id, card_name, market_price,
                    provider_observed_at, source_file, source_hash
                ) FROM STDIN
                """
            ) as copy:
                for row in rows:
                    copy.write_row(
                        (
                            row.provider_id,
                            row.card_name,
                            row.market_price,
                            row.provider_observed_at,
                            row.source_file,
                            row.source_hash,
                        )
                    )

            cursor.execute(
                """
                INSERT INTO practice_cards (provider_id, card_name)
                SELECT provider_id, card_name FROM incoming_prices
                ON CONFLICT (provider_id) DO UPDATE
                SET card_name = EXCLUDED.card_name
                WHERE practice_cards.card_name IS DISTINCT FROM EXCLUDED.card_name
                """
            )
            cursor.execute(
                """
                INSERT INTO practice_current_prices (
                    card_id, market_price, provider_observed_at,
                    source_file, source_hash
                )
                SELECT c.card_id, i.market_price, i.provider_observed_at,
                       i.source_file, i.source_hash
                FROM incoming_prices AS i
                JOIN practice_cards AS c USING (provider_id)
                ON CONFLICT (card_id) DO UPDATE SET
                    market_price = EXCLUDED.market_price,
                    provider_observed_at = EXCLUDED.provider_observed_at,
                    source_file = EXCLUDED.source_file,
                    source_hash = EXCLUDED.source_hash,
                    loaded_at = CURRENT_TIMESTAMP
                WHERE
                    EXCLUDED.provider_observed_at
                        > practice_current_prices.provider_observed_at
                    OR (
                        EXCLUDED.provider_observed_at
                            = practice_current_prices.provider_observed_at
                        AND practice_current_prices.source_hash IS DISTINCT FROM
                            EXCLUDED.source_hash
                    )
                """
            )
            counts["canonical_rows_affected"] = cursor.rowcount
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    load_dotenv()
    rows = parse_fixture(args.fixture)  # validation precedes DB connection
    print(json.dumps(load_rows(rows), indent=2))


if __name__ == "__main__":
    main()
```

## 4. Create the disposable database

Create a virtual environment and install only the declared dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` before running Python. Then create and initialize the practice
database. `psql` prompts for the administrator password:

```powershell
psql -h localhost -p 5432 -U postgres -d postgres -c "CREATE DATABASE learning_prices;"
psql -h localhost -p 5432 -U postgres -d learning_prices -f schema.sql
```

If `learning_prices` already exists from an earlier attempt, either keep it and
inspect the current state or remove **only that named practice database**:

```powershell
psql -h localhost -p 5432 -U postgres -d postgres -c "DROP DATABASE learning_prices WITH (FORCE);"
```

Never substitute your GraildTCG or another operational database name in that
cleanup command.

## 5. Run the behavioral tests

### First load: insert

```powershell
python .\load_fixture.py .\fixture\base.json
```

Expected classification:

```json
{"inserted": 1, "unchanged": 0, "canonical_rows_affected": 1}
```

Additional counters are present with value zero. One immutable raw file appears
under `raw/`; its name is the SHA-256 of the exact fixture bytes.

### Exact offline replay: true no-op

```powershell
python .\load_fixture.py .\fixture\base.json
```

Expected: `unchanged=1` and `canonical_rows_affected=0`. The same raw bytes map
to the same evidence file, and the upsert does not change `loaded_at`. This is a
stronger idempotency demonstration than merely keeping the row count at one.

### Newer provider observation: update

```powershell
python .\load_fixture.py .\fixture\newer.json
```

Expected: `updated_newer=1`, `canonical_rows_affected=1`, and final price 13.00
at `2026-01-02T00:00:00Z`.

### Older provider observation: protected no-op

```powershell
python .\load_fixture.py .\fixture\older.json
```

Expected: `older_skipped=1` and `canonical_rows_affected=0`. The tempting
999.00 value must not overwrite the newer snapshot.

### Malformed response: preserve then reject

```powershell
python .\load_fixture.py .\fixture\malformed.json
```

Expected: `ValueError: cards must be an array`, a nonzero process exit, a new
immutable raw file, and no database change. This demonstrates why raw evidence
preservation and validation are separate steps.

## 6. Verify the final database state

Save as `verify.sql`:

```sql
SELECT count(*) AS cards FROM practice_cards;                 -- 1
SELECT count(*) AS current_rows FROM practice_current_prices; -- 1

SELECT c.provider_id, c.card_name,
       p.market_price, p.provider_observed_at,
       length(p.source_hash) AS hash_length
FROM practice_cards AS c
JOIN practice_current_prices AS p USING (card_id);
-- 101 | Practice Dragon | 13.00 | 2026-01-02 00:00:00+00 | 64

SELECT count(*) AS orphan_rows
FROM practice_current_prices AS p
LEFT JOIN practice_cards AS c USING (card_id)
WHERE c.card_id IS NULL;                                      -- 0

SELECT count(*) AS negative_prices
FROM practice_current_prices
WHERE market_price < 0;                                       -- 0

SELECT * FROM practice_reporting;
-- exactly one row, with the same final price and provider timestamp
```

Run it:

```powershell
psql -h localhost -p 5432 -U postgres -d learning_prices -f verify.sql
(Get-ChildItem .\raw\snapshot_*.json).Count
```

After base, newer, older, and malformed fixtures, the raw count should be four;
the duplicate base replay creates no fifth file.

## 7. What rollback protects

All validation runs before `psycopg.connect()`. Database work then occurs in one
connection context. If `COPY`, the card upsert, the price upsert, or a constraint
fails, Psycopg rolls the transaction back. The raw snapshot remains because it
is source evidence, not a canonical database write.

To observe rollback, temporarily change `schema.sql` to require a maximum price
and replay `newer.json` into a newly created practice database. The loader
should fail without leaving only the card or only the price. Restore the schema
after the experiment.

## 8. Common errors

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `psql` is not recognized | PostgreSQL `bin` missing from `PATH` | add it or use the full executable path |
| password authentication failed | wrong user/password or `pg_hba.conf` policy | verify login in pgAdmin; correct `.env` and `-U` |
| database does not exist | create command not run or wrong port | connect to `postgres`, create `learning_prices` |
| `ModuleNotFoundError` | virtual environment inactive/dependencies absent | activate `.venv`; install requirements |
| `PGPASSWORD` missing | `.env` absent or still has placeholder | copy/edit `.env.example`; never commit `.env` |
| relation does not exist | `schema.sql` not executed in `learning_prices` | run the exact `psql ... -f schema.sql` command |
| `cards must be an array` | intentional malformed fixture or wrong JSON shape | inspect preserved raw file; correct the fixture |
| older test changes price | timestamp guard was altered | restore the production-style `WHERE` predicate |
| replay changes `loaded_at` | equal-hash no-op guard was removed | require same-time changed hash before update |

## 9. Optional Power BI check

Connect Power BI Desktop to PostgreSQL in Import mode and import only
`public.practice_reporting`. Set `market_price` to **Don't summarize**. A table
visual should show one Practice Dragon row at 13.00. Refreshing Power BI reads
PostgreSQL; it does not run the Python loader.

## Practice exercises

1. Add a second card with `market_price: null`. Predict the SQL and Power BI
   result before running it.
2. Create an equal-timestamp fixture with a changed price. Which counter and SQL
   branch should accept it?
3. Remove `source_hash` from the upsert predicate. Explain which kind of
   provider revision becomes invisible.
4. Extend the model with `practice_price_history` keyed by
   `(card_id, observation_date)`. Explain why its conflict and reporting
   behavior differs from a latest-snapshot table.

Solutions are in [Exercise answer key](16_EXERCISE_ANSWER_KEY.md#chapter-13--mini-pipeline).
