# Shared Kanban Multi-Agent Invariants

> Status: ACTIVE
> Scope: proyek pada project-control root node Hermes yang memakai Kanban.
> Project-specific business rules, model choices, dan approval gates tetap mengikuti `AGENTS.md` serta control folder proyek masing-masing.

## Tujuan

Mencegah pipeline berhenti setelah independent QA menemukan defect dan mencegah worker crash akibat provider/model task yang tidak eksplisit.

## Pre-execution plan gate

Sebelum graph coding dibuat atau task source-code dipromosikan ke `READY`, Planner/Lead wajib mengikuti [`PLAN_ASSURANCE_PROTOCOL.md`](PLAN_ASSURANCE_PROTOCOL.md). Gate tersebut memerlukan review paralel (coverage + adversarial), revisi, fresh E2E review, parity lintas-file, dan simulasi graph. `PLAN_GATE.md` harus `VERDICT: PASS`; QA kode di bawah ini baru berlaku sesudah eksekusi dimulai.

## Graph wajib

```text
Plan assurance PASS
  -> Coding
  -> independent QA
       -> PASS: complete QA; dispatcher boleh mempromosikan downstream
       -> FAIL teknis actionable:
            Coding revision
              -> independent QA retry
                   -> PASS: downstream boleh dipromosikan
                   -> FAIL: revision berikutnya dengan evidence baru
       -> kebutuhan manusia nyata: needs_input
```

Hermes Kanban memakai status teknis seperti `todo`, `ready`, `running`, `done`, dan `blocked`. Label proses seperti `QA_FAIL` atau `REVISION_REQUIRED` tidak otomatis membuat feedback edge. Orchestrator wajib membentuk revision dan QA retry secara eksplisit.

## Klasifikasi blocker

Defect kode yang sudah memiliki remediasi teknis spesifik bukan `needs_input`. Contoh: regression test, lint/type error, call-site yang melanggar invariant, atau diff yang tidak sesuai acceptance criteria.

Pada `APPROVAL_GATED`, gunakan `needs_input` hanya untuk keputusan manusia nyata:

- keputusan bisnis/arsitektur;
- migration/schema atau risiko data;
- credential/secret;
- destructive operation;
- biaya/cloud/public access;
- approval commit, push, release, deploy, atau production mutation.

Pada `FULL_AUTO`, action class di atas tidak menjadi `needs_input` bila standing approval masih `ACTIVE`, binding project/profile/repository/bot cocok, prerequisite teknis terpenuhi, dan audit action dicatat. Aksi di luar boundary atau yang berstatus prohibited tetap `BLOCKED`.

## Rewire dependency tanpa race

1. Pertahankan QA gagal dan seluruh evidence; jangan ubah menjadi PASS/done.
2. Buat Coding revision idempotent pada workspace terisolasi yang sesuai.
3. Buat independent QA retry sebagai child revision.
4. Link QA retry sebagai parent seluruh downstream child lama terlebih dahulu.
5. Baru unlink QA gagal lama dari downstream.
6. Jangan mempromosikan downstream secara manual untuk melewati QA retry.
7. Status `done` wajib memiliki test/verdict evidence.

Urutan link-before-unlink wajib karena unlink-first dapat membuka celah singkat tanpa parent dan membuat dispatcher mempromosikan downstream sebelum QA retry PASS.

## Provider/model worker

Setiap task executor wajib menyimpan provider dan model override yang eksplisit sesuai role/proyek. Jangan mengandalkan alias provider atau cache gateway.

Jika worker crash dengan pesan provider/credential tetapi direct profile probe berhasil:

1. jangan langsung mengubah secret;
2. bandingkan provider/model task dengan config profil efektif;
3. pin provider/model exact pada task;
4. unblock satu kali;
5. dispatch maksimal satu source writer;
6. verifikasi heartbeat melewati titik crash sebelumnya.

Mapping provider/model bersifat project-specific. Contoh ERP Tumbuh ada di repo `_docs/multi-agent-workflow.md` dan note Obsidian [[ERP Tumbuh - Invariant Kanban Multi-Agent]].

## Checklist lintas proyek

- Maksimal satu source writer pada ownership yang tumpang tindih.
- Workspace coding terisolasi dan tidak menimpa dirty shared worktree.
- QA independen dan read-only terhadap source.
- QA FAIL teknis mempunyai revision edge, bukan human blocker palsu.
- Downstream bergantung pada QA retry terbaru.
- Task executor memiliki provider/model override eksplisit.
- Worker memiliki heartbeat aktual.
- Tidak ada commit/push/deploy/migration/production mutation yang melewati policy dan gate proyek; `FULL_AUTO` hanya mengganti approval berulang di dalam boundary aktif, bukan technical gate.

## Sumber dan penggunaan

- Shared contract: `<project-control-root>/KANBAN_MULTI_AGENT_INVARIANTS.md`
- Setiap Planner/Lead Agent yang membuat graph Kanban harus membaca dokumen ini bersama aturan proyeknya.
