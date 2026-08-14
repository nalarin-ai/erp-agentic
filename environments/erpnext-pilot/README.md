# ERPNext Pilot Environment

## Status
`SYNTHETIC_ISOLATED`

## Security
- All secrets are synthetic and randomly generated.
- No real credentials, no live data, no production access.
- All ports bound to `127.0.0.1` only.
- `.env` file is `.gitignore`d and must never be committed.

## Quick Start

```bash
cd environments/erpnext-pilot

# 1. Generate synthetic secrets (one-time)
./generate-secrets.sh

# 2. Start isolated environment
./start.sh

# 3. Teardown (removes containers + volumes)
./teardown.sh
```

## Stack

| Component | Image | Port |
|---|---|---|
| MariaDB | `mariadb:11.8` | internal |
| Redis Cache | `redis:7-alpine` | internal |
| Redis Queue | `redis:7-alpine` | internal |
| ERPNext | `frappe/erpnext:v16.32.1` | `127.0.0.1:18080` |

## Evidence
- `docs/evidence/erpnext-runtime/` — health checks, backup/restore logs.
