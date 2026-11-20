# Chapter 5 — Working with APIs and JSON

## REST and HTTP in this project

A REST API exposes resources through URLs. GraildTCG sends HTTP GET requests to
`https://api.tcgapi.dev/v1` using `src/gmad/tcgapi_client.py::TcgApiClient`.
Authentication is the `X-API-Key` header; `Accept: application/json` requests
JSON; a project user-agent identifies the client.

`_get` supplies a timeout and calls `raise_for_status()`. Therefore HTTP 4xx/5xx
is an exception unless a specialized extractor, such as Task 9, intentionally
handles status codes and retries.

## Implemented endpoints

| Purpose | Method in `TcgApiClient` | Endpoint/parameters |
| --- | --- | --- |
| Set metadata | `get_set` | `GET /sets/{id}` |
| Catalog pages/current prices | `iter_set_card_pages` | `GET /sets/{id}/cards?page=&per_page=&type=Cards` |
| History | `get_bulk_history` | `GET /bulk/history?ids=&range=`; 1–50 IDs |
| Conditions | `get_bulk_conditions` | `GET /bulk/conditions?ids=`; 1–500 IDs |
| Prices/eBay data | `get_bulk_prices` | `GET /bulk/prices?ids=&include=`; 1–500 IDs |
| Individual sales | direct Requests session in Task 9 | `GET /cards/{id}/prices?include=ebay_sales` |

Catalog pagination stops only when `meta.has_more` is false. The loader verifies
that `meta.total` stays constant and that the final observed count matches the
configured expectation.

## Exact raw text and Decimal-aware parsing

`get_json_with_raw` returns both forms:

```python
raw_text = response.text
payload = json.loads(raw_text, parse_float=Decimal)
return payload, raw_text
```

The exact text is source evidence. `Decimal` prevents Python from immediately
turning JSON decimals into binary floats. That matters because observed shipping
values included `1.6099999999999999`.

## Sanitized real response shapes

Catalog/current row (`data/raw/tcgapi_current/.../cards_page_001.json`):

```json
{
  "id": 2163545,
  "printing": "Normal",
  "market_price": 0.22,
  "lowest_with_shipping": 0.19,
  "total_listings": 3,
  "price_updated_at": "2026-11-17T03:15:55.017Z"
}
```

History (`data` is an object keyed by card ID, whose value is an array):

```json
{"card_id": 983892, "date": "2025-06-02", "printing": "Normal",
 "market_price": 0, "low_price": null, "sales_volume": 0}
```

Conditions:

```json
{"card_id": 983892, "printing": "Normal", "condition": "Lightly Played",
 "language": "Japanese", "median_with_shipping": 1.64,
 "sample_count": 3, "last_updated_at": "2026-11-17T15:07:52.998Z"}
```

Graded summaries are nested under `ebay.graded` by raw grade label. A real
summary had `median_30d: null`, `sales_30d: 0`, but retained `last_price: 80`
and `last_sold: 2026-08-12`.

Individual sales are an `ebay.sales` array with `sold_date`, `price`,
`best_offer`, nullable `list_price`, nullable grade/condition, title, and URL.
No sale currency or stable ID was observed.

## Missing versus null versus absent

- JSON `null` becomes Python `None` and SQL `NULL`.
- Zero remains zero.
- An absent card key in an HTTP 200 bulk-history response is classified as
  provider-omitted/no-history and recorded in the manifest.
- An empty sales array is recorded separately from a missing array or request
  failure; it is not proof of zero marketplace activity.

Validators such as `_required_text`, `_positive_int`, `_optional_decimal`, and
`_timestamp` reject wrong types, negative numbers, blank strings, or malformed
dates before the database transaction.

## Rate limits, credits, retries, and observed contracts

The live history endpoint rejected 100 IDs and reported a maximum of 50, so the
client enforces 50 despite an earlier reference suggesting 100. This illustrates
the difference between documentation and observed behavior.

Task 8 projects credits, performs a quota probe, adds a 100-credit buffer, and
makes one bulk request only if it fits. Task 9 also enforces a 1,100-credit hard
ceiling and pessimistically reserves credit for every possible charged attempt.
It retries only network errors, HTTP 429, and 5xx, with bounded attempts and
backoff.

## Practice exercises

1. Take the condition example above and map every field to
   `ConditionPriceRow`. Identify values supplied by JSON, configuration,
   database identity, raw-file context, and hashing.
2. Parse `{"market_price": 1.6099999999999999}` once with ordinary `json.loads`
   and once with `parse_float=Decimal`. Compare `repr` and explain which value
   should reach `NUMERIC`.
3. Classify each case separately: HTTP 503, HTTP 200 with a missing card key,
   HTTP 200 with an empty sales array, and HTTP 200 with malformed `data`.
4. Write validation pseudocode that rejects a boolean card ID, negative price,
   naive timestamp, and blank printing before database loading.

Solutions are in [Exercise answer key](16_EXERCISE_ANSWER_KEY.md#chapter-5--apis-and-json).

