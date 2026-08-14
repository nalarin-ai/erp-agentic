# Writer Lease

- Status: `FREE`
- Last owner: hermes-executor (cron tick 2026-08-14T14:17Z)
- Last task: `CRM-001` — in progress, slice committed (`da23867`): CRM port contracts + fixture adapter + unit isolation proven (378/378 PASS; QA PASS_WITH_FINDINGS remediated). **Remaining untuk CRM-001 DONE:** adapter ERPNext CRM nyata (`src/adapters/erpnext_crm/**`) menjalankan contract suite yang sama vs pilot + fresh QA final + transition review.
- Released at: `2026-08-14T14:50:00Z`
- Recovery basis: HEAD `da23867` = trusted implementation base. Contract suite CRM siap di-bind ke adapter ERPNext: `tests/crm/test_fixture_crm.py` (mixin-style reusable pattern), `src/crm/port.py`. Ikuti pola ADP-002: ERPNext doctype Lead/Quotation/Customer, scope=company, seeder bila perlu.
