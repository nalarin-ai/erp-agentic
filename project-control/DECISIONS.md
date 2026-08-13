# Decisions

## D-001 — FULL_AUTO project-bound

- Decision: `FULL_AUTO`
- Status: `ACTIVE`
- Activated at: `2026-08-13T08:44:09Z`
- Source: Instruksi eksplisit Bos dari identitas Telegram allowlisted `233301028`; Bos memastikan credential aman dan memerintahkan aktivasi.
- Boundary: project `erp-kreasi-hebat`, profile `executor`, repository `/home/tejo/agentic/projects/erp-kreasi-hebat`, bot `@NalarinLinuxKreasiHebatBot`.
- Controls retained: plan gate, one-writer lease, least privilege, backup/rollback, tests, independent review, audit, and post-action verification.
- Revocation: `STOP FULL_AUTO` atau `APPROVAL_GATED`.

## D-002 — FULL_AUTO reaffirmed in executor Telegram

- Decision: Keep `FULL_AUTO` `ACTIVE` under the existing D-001 boundary.
- Reaffirmed at: `2026-08-13T08:52:39Z`
- Source: Explicit instruction from the same allowlisted Telegram identity `233301028`: “aktifkan full auto. telegram tetap di sini karena kamu eksekutor.”
- Effect: No boundary expansion; controls and revocation terms from D-001 remain unchanged.

## D-003 — ERP product selection remains evidence-gated

- Decision: `PROPOSED`, not final.
- ERPNext/Frappe is the maturity-first system-of-record candidate.
- ERPClaw is an experimental conversation-first comparator, not yet authorized as the official ledger.
- Final selection requires a synthetic pilot, permission/audit checks, Indonesian localization review, backup/restore proof, and current-baseline plan gate.

## D-004 — Separate operating brand from legal issuer

- Decision: `ACCEPTED` for discovery baseline.
- Operating units/brands share one office but keep separate sales pipelines because their sales teams compete.
- PT TKH is a distinct VAT-registered legal issuer for PPN transactions; the associated receivable payment must use an approved PT TKH bank account.
- Data model consequence: `operating_unit`, `sales_owner/scope`, `legal_issuer`, `tax_profile`, `invoice_series`, `receivable_ledger`, and `destination_bank_account` are explicit dimensions rather than one overloaded “company” field.
- Safety boundary: the ERP must not guess PPN or legal issuer from free-form chat. O-007 and O-008 must be resolved before production posting.

## D-005 — Unit-specific and shared bank-account mapping

- Decision: `ACCEPTED` for discovery baseline.
- Balonesia, Banyumedia, Pr1me, Contractor/Paving Block, and PT TKH each have their own/default receiving account.
- Heavy-equipment rental explicitly uses the same receiving account as Contractor/Paving Block; this is an approved shared-account mapping, not an inferred fallback.
- Some accounts may be shared by multiple operating units, but sharing requires an explicit allowlist.
- Account selection is constrained by legal issuer and tax treatment. A PT TKH-issued PPN transaction must use an approved PT TKH account.
- Security boundary: account numbers and banking credentials remain outside chat and project-control; records use opaque account IDs/display aliases with restricted configuration.
