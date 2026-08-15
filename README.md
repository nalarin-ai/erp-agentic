# ERP Agentic Nalarin.Ai

Provider-neutral ERP integration layer untuk multi-unit bisnis dengan separation of concerns yang tegas antara operating unit, legal issuer, sales ownership, dan financial identity.

## Fitur Utama

- **Multi-unit architecture**
  
- **Financial identity policy** — Deterministic issuer/tax/series/ledger/account resolution
- **Unit-scoped RBAC** — Actor-channel-unit assignment dengan fail-closed authorization
- **Idempotency & audit** — Durable mutation tracking dengan fencing dan crash recovery
- **ERPNext adapter** — Integration dengan ERPNext v16 (pinned)
- **Chat-to-invoice flow** — Draft → preview → approval → post → payment → audit

## Arsitektur

Lihat [docs/autopilot-architecture.html](docs/autopilot-architecture.html) untuk diagram visual.

```
src/
├── domain/           # Provider-neutral contracts (Money, FinancialIdentity, DocumentState)
├── authz/            # Identity, channel scope, RBAC
├── policy/           # Financial identity policy engine
├── mutations/        # Idempotency, durable store, fencing
├── audit/            # Append-only audit chain
├── adapters/         # ERPNext adapter + fixture
├── workflows/        # Invoice draft/post/payment flows
└── reconciliation/   # Recovery and reconciliation engine
```

## Quick Start

```bash
# Clone
git clone https://github.com/nalarin-ai/erp-kreasi-hebat.git
cd erp-kreasi-hebat

# Run tests
python3 -m unittest discover -s tests -v

# Start ERPNext pilot (synthetic, isolated)
cd environments/erpnext-pilot
./generate-secrets.sh
./start.sh
# → http://127.0.0.1:18080
```

## Development

- **TDD**: All features start with failing tests
- **Plan gate**: `python3 scripts/validate_plan_gate.py`
- **Mutation testing**: 190/190 mutants killed
- **Independent QA**: Read-only review required before commit

## License

MIT — see [LICENSE](LICENSE)

## Status

**Active development** — 14/30 tasks complete. See `project-control/STATUS.md` for current state.
