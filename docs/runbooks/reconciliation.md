# Runbook: Reconciliation Queue (REC-001)

> Status: ACTIVE (fixture lane)
> Scope: klasifikasi dan penyelesaian intent mutasi yang berakhir `UNCERTAIN` antara gateway dan ERP. Synthetic fixture only sampai PROD-001 APPROVED.

## Konsep

Satu intent mutasi (post invoice / record payment) yang hasilnya tidak pasti **tidak pernah di-retry buta**. Alurnya:

```text
UNCERTAIN outcome
  -> enqueue (idempotent per intent_key)
  -> classify (fenced, bounded)
       -> PRESENT     : RESOLVED, simpan official provider ref
       -> ABSENT      : SAFE_RETRYABLE, tepat satu retry terverifikasi
       -> AMBIGUOUS   : ESCALATED (operator), JANGAN auto-retry
       -> UNAVAILABLE : requeue terbatas (default 3x) lalu ESCALATED
```

## Operasi harian (fixture lane)

1. **Cek antrian**: `queue.depth()` — jumlah item aktif; `queue.stuck_items()` — item ESCALATED yang butuh tindakan operator.
2. **Item ESCALATED**: investigasi via `orphan_report` dan bukti provider. Jangan pernah menandai selesai tanpa klasifikasi terminal.
3. **Abandon** hanya untuk item ESCALATED dan wajib menyertakan reason operator (mis. nomor tiket dukungan provider). Abandon tidak menghapus audit; item tetap tersimpan dengan status `ABANDONED`.
4. **SAFE_RETRYABLE**: lakukan retry persis satu kali melalui jalur normal dengan idempotency key yang sama, lalu tutup dengan `mark_retried(item_id, resolution_ref=...)`.

## Klasifikasi

| Kelas | Arti | Tindakan |
|---|---|---|
| `PRESENT` | Provider memiliki dokumen/pembayaran; read-back konsisten dengan index query. | RESOLVED dengan `resolution_ref`. |
| `ABSENT` | Provider terverifikasi tidak memiliki record. | SAFE_RETRYABLE — satu retry aman. |
| `AMBIGUOUS` | Read-back dan query index saling kontradiksi. | ESCALATED — investigasi manual, dilarang auto-retry. |
| `UNAVAILABLE` | Provider tidak bisa menjawab authoritative (outage). | Requeue maks. `max_attempts`, lalu ESCALATED. |

## Fencing dan crash recovery

- Setiap klasifikasi berjalan di bawah fencing token monotonic per item; claimant kalah race mendapat `None` dan tidak menyentuh state.
- **Token pensiun saat transisi terminal.** Begitu `complete_classification` meninggalkan `CLASSIFYING`, token pemilik dicabut (kembali 0). Item `ESCALATED`/`SAFE_RETRYABLE` hanya bisa diproses lagi melalui `claim_item(item_id, fencing_token=baru)` dengan token yang lebih besar — override operator selalu meninggalkan jejak klaim baru.
- Worker crash saat `CLASSIFYING`: item tidak hilang — worker baru mengambil alih via `claim_item` dengan token lebih baru; token lama ditolak (`ItemLocked`).
- Error tak terduga saat klasifikasi (anchor ghost, read-back ditolak provider yang reachable) fail-closed ke `ESCALATED` dengan klasifikasi `AMBIGUOUS` — tidak ada item yang terdampar tak terlihat di `CLASSIFYING`.
- Deteksi `UNAVAILABLE` memakai sinyal ketik (`ping()`/pengecualian outage adapter), bukan pencocokan teks pesan error.
- Restart: proses baru membaca antrian; item `PENDING` di-claim via `claim_next`, item `CLASSIFYING`/`ESCALATED` diambil alih via `claim_item`, item `ESCALATED` menunggu keputusan operator. Tidak ada item yang hilang diam-diam.

## Orphan cross-check

`engine.orphan_report(known_draft_refs=..., known_evidence_refs=...)` menghasilkan:

- `erp_orphans`: dokumen POSTED di provider yang draft-nya tidak dikenal lokal (indikasi mutasi di luar jalur atau import tak terdaftar);
- `payment_orphans`: pembayaran di provider yang evidence ref-nya tidak dikenal lokal;
- `unresolved_items`: item queue yang masih terminal-uncertain (ESCALATED).

Jalankan sebagai bagian dari drill REC-001 bersama crash/restart matrix di `tests/reconciliation/`.

## Audit, replay, dan SLA (REC-QA round 3 closures)

- **Audit (F-01):** setiap transisi queue menambah record ke `AuditChain` internal (`REC_ENQUEUE`, `REC_CLAIM`, `REC_CLASSIFY_RESOLVED`, `REC_CLASSIFY_SAFE_RETRYABLE`, `REC_CLASSIFY_ESCALATED`, `REC_CLASSIFY_REQUEUED`, `REC_RETRIED`, `REC_ABANDONED`). Verifikasi integritas via `queue.verify_audit()`; inspeksi via `queue.audit_records()`.
- **Restart replay (F-02):** `queue.transition_log()` menghasilkan snapshot tiap transisi; `OperatorQueue.replay(log)` merekonstruksi state penuh (termasuk `escalated_from` guard dan sequence) setelah restart proses. Item PENDING kembali bisa di-claim, ESCALATED menunggu operator dengan fencing-token lama tetap pensiun.
- **SLA/alert (F-03):** tiap item membawa `enqueued_at`/`updated_at` (UTC, timezone-aware). `queue.overdue_items(max_age_seconds=...)` mengembalikan item aktif yang melewati ambang usia sejak transisi terakhir — dipakai untuk alert operator; item terminal tidak pernah overdue.

## Batasan fixture

- Adapter fixture in-memory; audit chain dan transition log REC-001 berada dalam-proses. Persistensi antar-proses memakai durable store pada task OPS/integrasi; kontrak replay sudah dibuktikan di `tests/reconciliation/test_engine.py::ReconciliationQaRound3RemediationTest`.
- Engine diketik terhadap protokol provider-neutral `ErpPort` (F-04), termasuk surface read-back `reconcile_post`/`reconcile_payment`/`known_draft_refs`/`payment_evidence_index`; adapter lain (mis. ERPNext di ADP-002) wajib memenuhi protokol yang sama.
- Tidak ada network, credential, atau data live. Semua refs synthetic opaque.
- Integrasi UI operator (`ui/reconciliation/**`) ditangani terpisah pada task UX; runbook ini adalah kontrak operasional lane fixture.
