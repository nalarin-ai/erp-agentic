# Duplicate Payment and Evidence Decision Table

- Status: `NORMATIVE_DRAFT`
- Principle: duplicate detection never discloses a protected existing record before re-authorization.

## Canonical fields

- `reference_namespace`: issuer/account alias/provider + normalized reference type.
- `normalized_reference`: Unicode-normalized, trimmed, case/rule normalized; raw value encrypted/restricted where sensitive.
- `evidence_checksum`: checksum of accepted normalized file bytes inside authorized tenant/unit namespace.
- financial tuple: invoice, amount, currency, payment date, destination account alias.
- idempotency/external reference remains the primary race-safe command key.

## Decision table

| Existing match | Incoming relation | Authorized disclosure | Outcome |
|---|---|---|---|
| Same command key + same hash | any retry | Return same safe result after current authorization | Idempotent replay |
| Same key + different hash | any | No existing details | Conflict; zero write |
| Same normalized payment reference, same invoice/amount/account | same unit and authorized | Existing safe alias/status | Treat as probable duplicate; no write |
| Same reference, different invoice/amount/account | any | No protected details to ordinary user | Controller/finance conflict queue; no write |
| Same evidence checksum, same invoice/payment | authorized | Existing safe alias/status | Reuse/link only if policy permits; otherwise duplicate denial |
| Same checksum, different invoice or unit | any | No record identity/details | Quarantine/conflict; cross-unit disclosure denied |
| Concurrent unmatched submissions | any | none until winner commits | Unique constraint/CAS chooses one; loser reconciles/conflicts |
| Evidence rejected/quarantined | any | reason safe for uploader | No payment write |

## Required tests

- Normalization variants and collision fixtures.
- Same/different invoice, amount, account, unit, and actor.
- Cross-unit checksum/reference side channel.
- Simultaneous claims.
- Authorization revoked between detection and response.
- Reversal then reuse policy.
- Checksum computed after safe decoding/limits; malicious archives never fully expanded.
