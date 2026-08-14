# ERPNext Runtime Evidence — EVAL-002

## Timestamp
`2026-08-14T19:15:00Z`

## Environment
| Component | Image | Status | Port |
|---|---|---|---|
| MariaDB | `mariadb:11.8` | Up | internal |
| Redis Cache | `redis:7-alpine` | Up | 6379 |
| Redis Queue | `redis:7-alpine` | Up | 6379 |
| ERPNext | `frappe/erpnext:v16.32.1` | Up | `127.0.0.1:18080` |

## Health Checks
```text
$ curl -s http://127.0.0.1:18080/api/method/ping
{"message":"pong"}

$ curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1:18080/
HTTP 200
```

## Installed Apps
```text
frappe  16.31.0 UNVERSIONED
erpnext 16.32.1 UNVERSIONED
```

## Notes
- All secrets are synthetic (generated via `openssl rand -hex 32`).
- All ports bound to `127.0.0.1` only.
- No production data, no live import, no external exposure.
- Teardown: `./teardown.sh` removes containers + volumes.

## Known Issues
- `create-site` container exits with code 1 due to Redis connection warning (cosmetic; site and apps are installed correctly).
- Redis queue endpoint in `create-site` defaults to `127.0.0.1:11311` instead of container name; backend works correctly.
