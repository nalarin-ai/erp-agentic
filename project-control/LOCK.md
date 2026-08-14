# Writer Lease

- Status: `CLAIMED`
- Owner: hermes-executor (cron tick 2026-08-14T14:17Z)
- Session/run ID: `crm-001-contracts-20260814T1417Z`
- Task ID: `CRM-001` — Unit-private CRM (ports + authorization matrix)
- Worktree: `/home/tejo/agentic/projects/erp-kreasi-hebat`
- Owned paths: `src/crm/**`, `src/adapters/erpnext_crm/**`, `tests/crm/**`
- Claimed at: `2026-08-14T14:17:00Z`
- Heartbeat: `2026-08-14T14:45:00Z` — CRM-001 QA remediation selesai. Independent QA (`deleg_a7a09d16`): PASS_WITH_FINDINGS — isolation inti terbukti; 2 mutan survive (test gap): F-001 cursor test no-op (next_cursor selalu None) dan F-002 export leak test buta; MEDIUM F-003 transfer cross-unit semantics belum dikunci, F-004 owner-level ACL (documented by-design); LOW F-005 limit/max_rows<1, F-006 malformed cursor ValueError, F-007 quotation lead_ref tanpa validasi; INFO F-008 payload by-reference, F-009 export tanpa durable audit (backlog integrasi). Remediasi TDD: 8 regression tests RED-first → GREEN (cursor test dengan 2 lead + assertIsNotNone; export distinct display_name + row_count; transfer cross-unit locked incl. no-read-back; limit/max_rows>=1 CrmDenied; cursor malformed → CrmDenied; quotation lead_ref in-scope CrmNotFound). Mutan M3/M6 dihunt ulang: KILLED. Full suite 378/378 PASS; compileall + diff-check + plan validator PASS. Commit next.
- Expires at: `2026-08-14T15:00:00Z` (15 min)
- Recovery basis: HEAD `53c60b3`, trusted base `a5a5b28`. 348/348 tests PASS pre-claim. CRM owned paths disjoint dari semua task lain (verified via EXPECTED_OWNED_PATHS di validator).
