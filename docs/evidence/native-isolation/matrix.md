# ISO-001 Native ERP Isolation — Probe Matrix

- Generated: 2026-08-14T23:46:58.114098+00:00
- Target: http://127.0.0.1:18080 (site `erpnext-pilot.localhost`), ERPNext pinned v16.32.1
- Raw evidence: `raw/probes-20260814.jsonl` (52 probes, latest run)

| Surface | Probes | Leak-positive probes | Denied (401/403/404) |
|---|---|---|---|
| attachment_file | 4 | 1 | 2 |
| direct_url | 8 | 2 | 6 |
| jobs_subscriptions | 6 | 0 | 6 |
| notification_activity | 5 | 0 | 2 |
| permission_mutation | 5 | 0 | 5 |
| report_export | 4 | 0 | 1 |
| rest_list | 13 | 4 | 0 |
| search_autocomplete | 7 | 3 | 0 |

## Leak-positive probes (markers observed in response bodies)

| Surface | Actor | Action | Status | Markers |
|---|---|---|---|---|
| attachment_file | iso-sales-p1@example.test | GET /api/resource/File (lead attachments) | 200 | iso-private-bm-001.txt |
| direct_url | iso-sales-bm@example.test | GET /api/resource/Customer/ISO-CUST-P1-001 (cross-unit) | 200 | ISO-CUST-P1-001 |
| direct_url | iso-sales-bm@example.test | existence-oracle 403-vs-404 split | 403 | status-oracle:403vs404 |
| rest_list | iso-sales-bm@example.test | Customer count inflation vs admin total | 200 | count-inflation:3==admin:3 |
| rest_list | iso-sales-p1@example.test | Customer count inflation vs admin total | 200 | count-inflation:3==admin:3 |
| rest_list | iso-sales-bm@example.test | GET /api/resource/Customer | 200 | ISO-CUST-P1-001 |
| rest_list | iso-sales-p1@example.test | GET /api/resource/Customer | 200 | ISO-CUST-BM-001 |
| search_autocomplete | iso-sales-bm@example.test | search_link Customer txt='ISO-CUST' | 200 | ISO-CUST-P1-001 |
| search_autocomplete | iso-sales-p1@example.test | search_link Customer txt='ISO-CUST' | 200 | ISO-CUST-BM-001 |
| search_autocomplete | iso-sales-bm@example.test | search_link Customer txt='ISO-CUST-P1-001' | 200 | ISO-CUST-P1-001 |
