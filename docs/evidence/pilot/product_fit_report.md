# PILOT-001 — Product-Fit / Localization / Configurability / Performance / Restore / Assumptions Report

Verdict pilot synthetic: **PASS untuk seluruh MVP-AC-01..15** pada permukaan synthetic (fixture adapters, tanpa network, opaque refs). Production **tetap BLOCKED** menunggu EXP-001 (qualified review) dan PROD-001 (explicit APPROVED/no-go record) — lihat `ac-12.md`.

## Coverage matrix (actual counts, 2026-08-15T02:45Z)

| AC | Scope | Tests | Evidence |
|---|---|---|---|
| MVP-AC-01 | Cross-sales isolation Banyumedia/Contractor | 8 | `ac-01.md` |
| MVP-AC-02 | Heavy Equipment→Contractor shared account (R-015) | 5 | `ac-02.md` |
| MVP-AC-03 | non-PPN + PT PPN correct tax paths | 7 | `ac-03.md` |
| MVP-AC-04 | Required ambiguity blocks posting | 5 | `ac-04.md` |
| MVP-AC-05 | Retry never duplicates (FND-004/REC-001) | 6 | `ac-05.md` |
| MVP-AC-06 | Unauthorized sensitive actions denied | 7 | `ac-06.md` |
| MVP-AC-07 | Number/PDF only after post | 7 | `ac-07.md` |
| MVP-AC-08 | Payment evidence + correct AR | 7 | `ac-08.md` |
| MVP-AC-09 | Durable audit/readback/redaction | 7 | `ac-09.md` |
| MVP-AC-10 | Export/backup/isolated restore (OPS-001) | 9 (1 skip by-design) | `ac-10.md` |
| MVP-AC-11 | Compact/wide/a11y/recovery UX view-models | 13 | `ac-11.md` |
| MVP-AC-12 | Assumptions reported; production blocked | 5 | `ac-12.md` |
| MVP-AC-13 | Distinct unit branding + immutable snapshot | 4 | `ac-13.md` |
| MVP-AC-14 | Multi-unit exactly-one-active-context | 9 | `ac-14.md` |
| MVP-AC-15 | No-hardcode onboarding/config lifecycle | 11 | `ac-15.md` |

Total focused pilot suite: **110 tests, OK (1 skip by-design)** — `python3 -m unittest discover -s tests.e2e.pilot -t .`.

## Product-fit

Seluruh journey inti (draft → review → post → payment → reversal; CRM lead/search/export; multi-unit selection; owner & receivables reports) berjalan end-to-end pada komponen produksi nyata di atas fixture adapters. Tidak ada kebutuhan patching `src/` selama pilot — semua kriteria terpenuhi oleh kontrak yang ada.

## Localization

- Money formatting terpusat (`_format_money`, Decimal) — konsisten IDR; tidak ada locale branch per unit.
- Branding per-unit (template + logo) versi-controlled; snapshot posted immutable (AC-13).
- Finding F-c (INFO): fixture adapter money scaling `1500000` vs `1500000.00` — kosmetik fixture, bukan defect produksi.

## Configurability

- Onboarding unit baru murni konfigurasi (catalog + settings draft→activate→rollback), dibuktikan dengan unit synthetic ZEPHYR_LABS (AC-15) — nol branch per-nama-unit di `src/` (AST-aware scan).
- Financial identity hanya settable via trusted-issuer catalog (FND-003); settings schema menolak unknown/script/invalid-ref/unauthorized/CAS-conflict/rollback-mismatch.
- Finding F-d (INFO): satu sebutan nama unit di docstring adapter CRM (bukan logika) — terdokumentasi di `ac-15.md`.

## Performance

- Focused suite 110 tests selesai < 1 detik pada fixture adapters; tidak ada N+1 pada path report (aggregasi owner/receivables diuji scope-bounded).
- Tidak ada target latency produksi yang diklaim dari fixture; pengukuran live ditunda ke gate PROD-001.

## Restore / operasional

- Backup fixture-mode: manifest lengkap (REQUIRED_STORES) + sha256; restore_verify isolated sukses; corrupt/missing/tampered/inconsistent semua ditolak; pilot-mode guard menolak tanpa acknowledgement flag (AC-10).
- Retry/idempotency aman terhadap stale worker & lost response (AC-05); blind retry di-fence sampai klasifikasi (REC-001).

## Assumptions (ringkasan — daftar lengkap di `ac-12.md`)

1. Fixture adapters = kontrak; validasi live ERPNext sudah dicakup ISO-001/ISOFIX-001 (gateway-only final architecture) dan suite integrasi.
2. Harness `_CODE_BY_REF` workaround untuk underscore catalog codes (HEAVY_EQUIPMENT, PT_TKH_OPS) — latent source limitation terdokumentasi (`ac-02.md`), bukan bypass.
3. Workflow `audit_events()` in-memory tanpa hash-chain; hash-chain ada pada AuditChain consumers (FND-004 lane backlog, F-009).
4. 2 FAIL pre-existing di `tests/integration` (state-dependent fixture: `test_export_is_scope_bounded_with_evidence`, `test_payment_evidence_index`) — backlog teknis terdaftar, bukan regresi pilot.
5. Live-state suites (`tests/security/isolation_final/test_qa_remediation`, sebagian `tests/integration/erpnext`) bergantung state pilot ERPNext dan dapat flaky; diverifikasi gagal identik pada baseline stashed → bukan regresi slice manapun.

## Residual risk

- Production go/no-go belum boleh: EXP-001 (BLOCKED_OWNER_EXPERT) + MIGDEC-001 (BLOCKED_OWNER_INPUT) + PROD-001 harus selesai dulu.
- Backlog teknis: marker-filtered assertion untuk 2 fixture state-dependent tests; workflow-level durable hash-chained audit (FND-004 lane).
