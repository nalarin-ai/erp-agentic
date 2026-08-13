# Plan Assurance Protocol

> **Status:** ACTIVE
> **Scope:** Proyek yang masuk ke autonomous coding loop melalui project-control root pada node Hermes terkait.
> **Precedence:** Aturan repo (`AGENTS.md`), keamanan, dan approval proyek selalu menang. Dokumen ini mengatur kapan plan boleh menghasilkan task eksekusi.

## Tujuan

Mencegah loop mengimplementasikan plan yang terlihat lengkap tetapi kehilangan requirement, jalur E2E, dependency, failure state, verifikasi, operasi, atau batas approval. Review tidak boleh menjadi sekadar persetujuan prose.

Tidak ada task source-code boleh berstatus `READY`, di-claim, atau dieksekusi sebelum `PLAN_GATE.md` menyatakan `VERDICT: PASS` untuk baseline plan yang sama.

## Artefak minimum per proyek

Simpan pada `projects/<project-slug>/`:

- `PROJECT.md` — tujuan, repo, scope, non-goal, approval boundary.
- `REQUIREMENTS.md` — requirement bernomor dan acceptance evidence.
- `EXECUTION_PLAN.md` — task implementasi, dependency, owner path/worktree, langkah, dan done-when.
- `TASK_QUEUE.md` — graph status dan dependency yang identik dengan plan.
- `TEST_STRATEGY.md` — gate unit/integrasi/E2E/build/ops serta target aktualnya.
- `RISK_REGISTER.md` — risk, mitigasi, residual risk, dan approval yang diperlukan.
- `PLAN_REVIEW.md` — finding dan closure evidence dari semua review pass.
- `PLAN_GATE.md` — baseline identity dan verdict eksekusi.

Plan bukan artefak tunggal. Semua dokumen di atas adalah satu baseline dan memakai ID requirement/task yang sama.

## Status dan transisi

```text
INTAKE
 -> DISCOVERY
 -> PLAN_DRAFT
 -> PLAN_REVIEW_PARALLEL
 -> PLAN_REVISION
 -> FRESH_REVIEW
 -> PLAN_GATE
      -> PASS: task eksekusi dapat menjadi BACKLOG/READY sesuai dependency
      -> REVISE: kembali ke PLAN_REVISION
      -> BLOCKED_PLAN: hanya bila perlu keputusan Bos yang nyata

READY -> CLAIMED -> DOING -> REVIEW -> EVIDENCE -> VERIFIED -> DONE
```

`BLOCKED_PLAN` hanya untuk keputusan bisnis/arsitektur, data/migrasi, credential, biaya, akses publik, atau risiko produksi yang tidak bisa diputuskan dengan evidence lokal. Finding teknis yang memiliki solusi tidak boleh dialihkan menjadi pertanyaan Bos.

## Review berlapis

### Pass 0 — discovery & baseline (oleh Hermes)

Sebelum menulis plan, baca kontrak repo, source relevan, test/runtime/deploy aktual, git status, dan batas approval. Pisahkan observed fact dari asumsi. Jangan menyebut API, DB, background job, atau deploy seolah ada bila belum dibuktikan.

### Pass 1 dan 2 — review paralel, read-only

Kedua reviewer memakai konteks terpisah dan tidak mengubah plan.

1. **Traceability & completeness reviewer**
   - Setiap requirement memiliki task, acceptance evidence, dan test target.
   - Semua jalur utama mencakup UI → API → DB → job/integrasi (bila ada) → observability.
   - Semua error/empty/loading/auth/permission/offline state memiliki perilaku dan test.
   - Tidak ada placeholder seperti “handle edge cases”, “test later”, atau “sesuai kebutuhan”.

2. **Adversarial engineering reviewer**
   - Cari dependency cycle, task yang mustahil READY, race, shared-file/worktree conflict, data/security/privacy risk, rollback gap, false-completion path, dan human approval yang tidak perlu.
   - Simulasikan dependency graph pada kondisi resource lengkap, parsial, dan tidak tersedia.
   - Pastikan external/hardware/integrasi yang belum tersedia tidak menghentikan track independen, tetapi final release tetap bergantung pada proof nyata.

### Pass 3 — E2E/release reviewer, fresh context

Dijalankan **setelah** seluruh finding Pass 1–2 direvisi. Reviewer ini tidak boleh menjadi penulis plan atau penutup finding sendiri.

- Audit ulang seluruh baseline, bukan hanya diff revisi.
- Pastikan flow pengguna utama dapat dibuktikan end-to-end; test unit saja tidak cukup.
- Cocokkan plan ↔ queue ↔ test strategy ↔ risk register ↔ approval gate secara lintas-file.
- Pastikan observability/health/rollback dan evidence directory dimasukkan bila aplikasi menjalankan API, DB, job, atau layanan.

## Finding dan closure

Setiap finding punya ID tetap, severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), sumber/reviewer, lokasi requirement/task, consequence, rekomendasi, status, dan bukti closure.

- `CRITICAL`/`HIGH`: harus `RESOLVED` dan dinilai ulang fresh sebelum PASS.
- `MEDIUM`: harus di-resolve atau diterima secara eksplisit dalam `RISK_REGISTER.md` dengan alasan dan owner.
- `LOW`: boleh dijadwalkan, tetapi tidak boleh menyamarkan gap acceptance atau keamanan.
- “Looks good”, exit code, atau prose reviewer tanpa traceability bukan verdict.

Setelah revisi, lakukan review ulang atas **baseline penuh**. Penulis plan dilarang self-certify; reviewer boleh menyatakan clean hanya dengan checklist dan bukti yang eksplisit.

## Gate mekanis wajib

Sebelum `PLAN_GATE: PASS`, jalankan dan simpan output:

1. Parity requirement: setiap requirement memiliki ≥1 task dan ≥1 acceptance evidence.
2. Parity task: task di `EXECUTION_PLAN.md` sama dengan `TASK_QUEUE.md`; dependency identik dan acyclic.
3. Readiness: hanya task dengan dependency yang benar-benar satisfied boleh `READY`.
4. Granularity: tiap task memiliki path/scope, minimal tiga langkah konkret, test, dan `Done when` machine-checkable.
5. E2E matrix: setiap user journey utama memetakan UI, API/contract, persistence/integration, failure state, observability, dan proof.
6. Approval matrix: policy harus tepat `APPROVAL_GATED` atau `FULL_AUTO`. Pada `APPROVAL_GATED`, setiap protected action memerlukan approval spesifik. Pada `FULL_AUTO`, standing approval harus `ACTIVE` dan terikat ke project/profile/repository/bot node ini; kontrol teknis tetap wajib.
7. Freshness: hash/commit atau timestamp baseline plan dicatat di `PLAN_GATE.md`; perubahan material sesudah PASS membatalkan gate dan kembali ke review.

Jalankan `python scripts/validate_plan_gate.py projects/<project-slug>` untuk structural checks. Validator bukan pengganti review semantik/adversarial.

## Format verdict

`PLAN_GATE.md` wajib memuat:

```text
Baseline-ID: <git SHA atau SHA-256 manifest>
VERDICT: PASS | REVISE | BLOCKED_PLAN
Pass-1/2 findings: <total / unresolved critical-high>
Fresh review: PASS | REVISE
Structural validator: PASS | FAIL
Graph simulation: PASS | FAIL
Approval boundaries checked: PASS | FAIL
Authorized execution scope: <task IDs>
Residual risks: <IDs atau none>
```

## Perilaku loop

- Loop memilih task actionable, bukan task pertama yang terlihat.
- Dua tick tanpa task maju: hentikan loop dan laporkan evidence; jangan berpura-pura bekerja.
- Jika review menemukan gap teknis: revisi dan fresh-review; jangan minta Bos untuk defect yang dapat diselesaikan lokal.
- Maksimal tiga siklus review-revision untuk baseline yang sama. Sesudah itu Hermes membuat `BLOCKED_PLAN` hanya bila ada trade-off/keputusan nyata; jika tidak, pecah plan dan lanjutkan track independen.
- Ketika eksekusi mengungkap asumsi plan salah, buat Architecture Change Proposal/plan amendment, audit dampak dependency, dan jalankan ulang gate untuk task terdampak. Tidak ada perubahan material secara diam-diam.

## Hubungan dengan QA kode

Gate ini hanya membuka eksekusi. Sesudah coding, `KANBAN_MULTI_AGENT_INVARIANTS.md` tetap wajib: independent QA FAIL → revision → independent QA retry, dengan evidence dan rewire dependency yang aman.
