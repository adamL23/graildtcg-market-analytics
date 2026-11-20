"""Minimal authenticated client for the TCGAPI.dev endpoints used by ETL."""

from decimal import Decimal
import json
import os
from typing import Any, Iterator

import requests


BASE_URL = "https://api.tcgapi.dev/v1"


class TcgApiClient:
    """Fetch set metadata and paginated card catalogs without logging secrets."""

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 30):
        api_key = api_key or os.getenv("TCGAPI_KEY")
        if not api_key or api_key == "replace_me":
            raise ValueError("TCGAPI_KEY is missing from the project .env file.")

        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-API-Key": api_key,
                "Accept": "application/json",
                "User-Agent": "GraildTCG-GMAD/0.1",
            }
        )

    def get_json(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._get(endpoint, params)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected an object response from {endpoint}.")
        return payload

    def get_json_with_raw(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], str]:
        """Return exact response text plus Decimal-aware parsed JSON."""

        response = self._get(endpoint, params)
        raw_text = response.text
        payload = json.loads(raw_text, parse_float=Decimal)
        if not isinstance(payload, dict):
            raise ValueError(f"Expected an object response from {endpoint}.")
        return payload, raw_text

    def _get(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> requests.Response:
        response = self.session.get(
            f"{BASE_URL}/{endpoint.lstrip('/')}",
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response

    def get_set(self, set_id: int) -> dict[str, Any]:
        return self.get_json(f"sets/{set_id}")

    def iter_set_card_pages(
        self, set_id: int, per_page: int = 100
    ) -> Iterator[tuple[int, dict[str, Any]]]:
        page = 1
        while True:
            payload = self.get_json(
                f"sets/{set_id}/cards",
                {"page": page, "per_page": per_page, "type": "Cards"},
            )
            yield page, payload

            meta = payload.get("meta")
            if not isinstance(meta, dict):
                raise ValueError(f"Set {set_id} card response is missing meta.")
            if not meta.get("has_more"):
                break
            page += 1

    def get_bulk_history(
        self, card_ids: list[int], history_range: str = "all"
    ) -> tuple[dict[str, Any], str]:
        if not card_ids or len(card_ids) > 50:
            raise ValueError("Bulk history requires between 1 and 50 card IDs.")
        return self.get_json_with_raw(
            "bulk/history",
            {
                "ids": ",".join(str(card_id) for card_id in card_ids),
                "range": history_range,
            },
        )

    def get_bulk_conditions(
        self, card_ids: list[int]
    ) -> tuple[dict[str, Any], str]:
        if not card_ids or len(card_ids) > 500:
            raise ValueError("Bulk conditions requires between 1 and 500 card IDs.")
        return self.get_json_with_raw(
            "bulk/conditions",
            {"ids": ",".join(str(card_id) for card_id in card_ids)},
        )

    def get_bulk_prices(
        self, card_ids: list[int], include: str | None = None
    ) -> tuple[dict[str, Any], str]:
        if not card_ids or len(card_ids) > 500:
            raise ValueError("Bulk prices requires between 1 and 500 card IDs.")
        params: dict[str, Any] = {
            "ids": ",".join(str(card_id) for card_id in card_ids)
        }
        if include is not None:
            params["include"] = include
        return self.get_json_with_raw("bulk/prices", params)

