# UX Specification — ERP Kreasi Hebat MVP

- Status: `DRAFT`
- Depends on: `UX_DISCOVERY.md`, `PRD.md`, `RBAC_AND_POLICY.md`.

## 1. Chat draft-invoice flow

### Entry
User sends a natural-language invoice request in an allowlisted chat.

### Response contract

1. **Scope resolved:** show unit and requester alias only when safe. If the actor has multiple eligible units and context is ambiguous, present an accessible selector containing only assigned active units; do not continue until exactly one unit is selected.
2. **Missing fields:** ask only for missing required fields, with examples but no invented defaults.
3. **Blocked configuration:** state which category is unresolved (`legal issuer`, `PPN profile`, `destination account`) and direct to authorized finance/controller; do not reveal hidden alternatives.
4. **Preview:** show:
   - unit logo/branding name and template version;
   - unit and sales owner;
   - customer alias/name as authorized;
   - items/services, quantity, price, discount;
   - subtotal/tax/total/currency;
   - legal issuer;
   - PPN/non-PPN state;
   - destination account alias/masked label;
   - issue/due dates;
   - action reference and expiry/version.
5. **Post result:** say `posted and verified` only after ERP read-back. Otherwise show `processing`, `failed without mutation`, or `reconciliation required` truthfully.

### Cancel/edit
Users can cancel the draft or revise fields before posting. Changing material fields invalidates the previous preview/action hash.

### Unit switching
The active unit is always visible near the primary navigation/action. Switching requires confirmation when a draft exists, clears scoped search/results, invalidates the preview/action hash, and reloads permitted CRM/options. Keyboard users can reach, operate, and dismiss the selector; focus returns to the unit control. Empty assignment, revoked assignment, and stale-context states provide a safe escalation without revealing other units.

## 2. Finance review screen

### Layout

- Header: document state, unit, issuer, invoice type, correlation/reference.
- Branding preview: selected unit logo/template version, visually separated from the legal-issuer/tax/account policy card.
- Main: customer and line items; totals and due date.
- Policy card: PPN state, issuer, invoice series, account alias, validation results.
- Audit sidebar/section: requester, source, timestamps, changes, previous review.
- Footer actions based on role: `Return for correction`, `Post invoice`, `Cancel`.

### Safety

- Primary posting action is visually distinct but never the only keyboard path.
- A confirmation summarizes irreversible effects: official number, ledger posting, tax/issuer, destination account.
- Focus enters confirmation heading, remains contained, and returns to trigger on cancel.
- Errors preserve entered/review context and identify recoverable next action.

## 3. Receivables screen

Filters: unit, issuer, sales owner, customer, status, aging bucket, due date. Default filters honor role scope. Owner roll-up explicitly labels aggregation and never implies one merged ledger.

Each row/card shows safe customer identity, unit, issuer, invoice reference, due date, open amount, status, and allowed actions. Status uses text/icon plus color, not color alone.

## 4. Payment evidence flow

Fields: invoice, amount, currency, payment date, account alias, reference alias, evidence upload, note/reason. Validate remaining balance and account policy before submission. Duplicate evidence/reference presents existing record or controller conflict workflow.

## 5. Permission-denied behavior

Use generic language such as “Anda tidak memiliki akses untuk tindakan ini pada unit tersebut.” Do not confirm protected record/customer existence. Provide safe escalation path to controller without exposing identities beyond authorization.

## 6. Responsive contract

- Compact target: 360–430 CSS px; no horizontal page overflow.
- Wide target: 1280+ CSS px; use columns/sidebar where supported.
- Tables become labeled cards or controlled scroll regions with accessible headers on compact screens.
- Touch targets meet platform-supported accessibility guidance; key actions remain reachable without hover.

## 7. Keyboard and accessibility

- Logical tab order follows visual/task order.
- Visible focus on all interactive elements.
- Native buttons/links/inputs and programmatic labels.
- Errors linked to fields and summarized at form top when multiple.
- Live regions only for real asynchronous outcomes.
- Reduced motion disables non-essential transitions.
- Indonesian copy avoids unexplained accounting/technical jargon; provide concise help text.

## 8. Content examples

### Missing data
`Draft belum dibuat. Mohon lengkapi: pelanggan, tanggal jatuh tempo, dan apakah transaksi memakai PT TKH/PPN.`

### Preview warning
`Periksa penerbit dan rekening. Setelah diposting, nomor resmi dan jurnal dibuat oleh ERP.`

### Verified success
`Invoice berhasil diposting dan diverifikasi di ERP. Referensi: INV-TEST-…`

### Uncertain state
`ERP mungkin telah menerima transaksi, tetapi hasil belum dapat diverifikasi. Jangan ulangi. Rekonsiliasi sedang diperlukan dengan referensi …`

## 9. UX acceptance evidence

- Component assertions for all state inventory items.
- E2E: draft → preview → post → PDF/receivable using synthetic data.
- E2E failure: unauthorized cross-unit action denied without disclosure.
- E2E recovery: simulated timeout after ERP mutation reconciles without duplicate.
- E2E multi-unit: assigned user selects Banyumedia then Contractor, sees only scoped data, receives matching branding, and cannot reuse a Banyumedia preview in Contractor context.
- E2E branding: two unit PDFs use distinct synthetic logos/templates while issuer/tax/ledger/account remain policy-derived; historical PDF snapshot is unchanged after branding version update.
- Screenshots compact/wide for review and receivable pages.
- Keyboard/focus audit for post confirmation and payment evidence.
- Independent UX/a11y review after implementation.

## 10. Additional journey/state contracts

| Journey | Entry | Loading/empty | Error/denied/offline | Allowed recovery | Persistence/event | Test |
|---|---|---|---|---|---|---|
| Overdue/reminder | authorized aging view or schedule | skeleton; “tidak ada piutang jatuh tempo” | destination denied, channel offline, invoice already paid | edit/cancel queued reminder; bounded retry | outbox + reminder terminal event | UX-J06 |
| Lead conflict | safe duplicate signal | controller queue empty state | ordinary sales sees no other-unit identity | controller assigns/closes with reason | conflict audit event | UX-J07 |
| Unit onboarding | admin starts config wizard | preview pending | invalid issuer/ledger/account/role mapping | revise/rollback before activation | versioned config audit | UX-J08 |
| Cancel/reversal | posted record and authorized role | reason/impact loading | unsupported ERP state, payment/delivery race | abort or reconcile; never hard delete | reversal mutation + readback | UX-J09 |
| Offline/retry | pending draft/delivery | explicit local/pending state | no false “success” | retry same idempotency key; uncertain state routes to reconciliation | intent/outbox state | UX-J10 |
| Empty report | authorized scoped query | skeleton then empty explanation | query denied or service unavailable | adjust filters/retry | query outcome event | UX-J11 |
| Evidence rejection | payment form upload | scan/quarantine state | type/size/malware/duplicate/privacy-safe rejection | replace/remove; controller conflict if authorized | evidence terminal event; no payment write | UX-J12 |

## 11. Duplicate payment/evidence UX

Follow `DUPLICATE_PAYMENT_POLICY.md`. Never reveal a matched invoice, customer, amount, account, unit, or evidence from another scope. A safe same-scope replay may show only the existing record alias/status the current actor is independently allowed to view. Conflict actions are limited to finance/controller roles and remain audited.

## 12. Unit settings UX

The authorized settings screen groups variables into Branding, Documents, Sales, Approval, Finance mappings, and Modules. It shows current version/effective date and supports `Edit draft`, `Validate`, `Preview`, `Activate`, and `Rollback` according to role.

- Field controls derive from the typed setting schema; no arbitrary JSON/script editor is exposed to ordinary admins.
- Branding preview renders synthetic quotation/invoice output and clearly separates unit branding from legal issuer/tax/account identity.
- Validation errors identify the exact setting and safe recovery without exposing protected account or tax data.
- Activation confirmation lists affected unit, changed keys, effective time, preview invalidation, and rollback target.
- Compact and wide layouts, keyboard/focus order, denied/read-only state, unsaved changes, concurrent version conflict, invalid reference, activation success/failure, and rollback are required test states.
