# Chapter 11 — Challenges and Engineering Tradeoffs

## Confirmed challenges

### Language-specific catalog coverage

All 459 `pokemon-japan` set rows were checked before accepting Japanese Mega
Brave (`1900041`) and Mega Symphonia (`1900209`). The default Pokémon and One
Piece catalogs were not treated as language-neutral. Gem Pack Vol. 6 and
Japanese OP-17 were absent after successful catalog/search requests, so they are
missing coverage—not failed requests. The allowlist keeps them unresolved.

**Alternative rejected:** substitute English versions or invent an ID. That
would satisfy row counts while corrupting language identity.

### API contracts and limits

The history endpoint's live 50-ID limit differed from an earlier 100-ID
reference. The implementation follows verified behavior and validates batch
size in both config and client. Individual-sale responses exposed no pagination
or totals, so the system does not claim full marketplace completeness.

### Financial representation

History required four decimals, while other responses contained long
floating-point artifacts. Exact `NUMERIC` values preserve the provider evidence;
reporting may round for display later. Binary `FLOAT` would introduce additional
representation uncertainty.

### Incomplete and stale market data

One card had no history, one current market price was null, and a current row
could retain a price alongside `no_market_price_since`. Cache responses may omit
future cards. The design reports coverage, retains last accepted state, and
keeps provider/source time separate from load time.

### Grading inconsistency

Provider labels include PSA, BGS, CGC, ACE, TAG, SGC, and generic text. Phase 1
stores raw labels instead of prematurely parsing a fragile enum. Normalization
and confidence rules are backlog work.

### Individual-sale identity

No stable sale ID exists. URLs were stable during a repeated sample but are not
documented as unique transactions. Fingerprints excluding URL were provably
duplicated across different URLs. The chosen observation model is honest and
replayable, though it limits cross-snapshot transaction analysis.

### Credits and retries

Bulk graded extraction cost 482 credits; individual sales cost 962 card credits.
The design separates paid extraction from free offline replay, uses safety
buffers, and pessimistically reserves retry cost. This is more operational work
than a naive retry loop, but prevents a test run from exhausting quota.

### Windows and OneDrive

OneDrive temporarily locked Task 9 manifest replacements. Exact response bodies
were already persisted, so resume recovered them without requesting again.
Atomic writes plus short retries were sufficient for the MVP. Object storage or
a run database would be more robust at production scale.

### Database and reporting security

Using one superuser everywhere would be simpler but dangerous. GraildTCG uses a
restricted application owner and a separate view-only reporting login. The
tradeoff is extra setup and credential files; the benefit is a smaller blast
radius.

## Confirmed problem versus future risk

| Status | Example |
| --- | --- |
| Confirmed | long price precision, missing catalogs, 50-ID limit, OneDrive locks, no sale ID |
| Possible future risk | provider schema drift, multiple snapshot confusion, growing raw storage |
| Deferred enhancement | grade normalization, monitoring, cloud orchestration, incremental Power BI refresh |

Do not write future risks as if an incident already occurred. Conversely, do
not hide confirmed limitations behind generic “API quality” language.

## Exercise

Pick one alternative design—scraping eBay, storing raw JSON only, or assigning a
synthetic sale ID. Write its short-term advantage and three integrity or
operational costs compared with the implemented design.

Example answer: [exercise answer key](16_EXERCISE_ANSWER_KEY.md#chapter-11--challenges-and-tradeoffs).

