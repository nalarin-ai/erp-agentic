# ISOFIX-001 Final Isolation Architecture — Probe Matrix

- Generated: 2026-08-15T01:03:43.352829+00:00
- Target: http://127.0.0.1:18080 (site `erpnext-pilot.localhost`), ERPNext pinned v16.32.1 (gateway-only final architecture)
- Raw evidence: `raw/probes-20260815.jsonl` (22 probes, latest run)

| Surface | Probes | Leak-positive probes | Denied (401/403/404) |
|---|---|---|---|
| final-gateway-crm | 5 | 0 | 2 |
| final-gateway-erp | 1 | 0 | 0 |
| final-migration | 6 | 0 | 0 |
| final-native-api | 2 | 0 | 2 |
| final-native-desk | 1 | 0 | 0 |
| final-native-direct | 1 | 0 | 1 |
| final-native-files | 2 | 0 | 2 |
| final-native-login | 2 | 0 | 2 |
| final-native-reports | 1 | 0 | 1 |
| final-native-search | 1 | 0 | 1 |

**Leak-positive probes (latest run): 0**

No leak-positive probes — every final-architecture surface clean.
