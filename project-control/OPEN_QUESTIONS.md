# Open Questions and Owner/Expert Inbox

- Status: `OPEN`
- Rule: do not place account numbers, tokens, taxpayer IDs, passwords, or live customer/employee data here.

## Product decisions

| ID | Needed by | Question | Safe default while open | Status |
|---|---|---|---|---|
| O-002 | Pilot plan | Which unit and invoice type is the first synthetic pilot? | Banyumedia service invoice as a non-live fixture; include a separate PT TKH PPN negative/compatibility fixture | OPEN |
| O-003 | Workflow config | Required invoice fields, numbering, currencies, approval thresholds, and payment-evidence rules? | IDR only; no posting when unknown; ERP-generated number | OPEN |
| O-004 | RBAC | Named users/roles and approval thresholds? | Default deny; fixture personas only | OPEN |
| O-005 | Capacity/import | User count, monthly volume, existing Excel shapes, retention, reports? | Design for small-office pilot; measure before tuning | OPEN |
| O-006 | Product evaluation | ERPNext only or ERPNext vs ERPClaw side-by-side pilot? | ERPNext primary; ERPClaw comparator remains optional/isolated | OPEN |
| O-007 | Legal/config | Complete list of legal “bendera,” tax status, invoice series, opaque account aliases, and allowed unit mappings? | Unknown mappings blocked | PARTIAL |
| O-008 | Tax policy | Deterministic rule for PT TKH/PPN path and authorized override/evidence? | Explicit finance selection from allowed policy; no AI inference | OPEN |
| O-009 | Sales isolation | Are customer master, lead, pricing, quotation, commission, and reports all unit-private? | All unit-private; owner explicit roll-up | OPEN |
| O-011 | Recovery | Required RPO/RTO and backup destination? | No production until chosen and restore-tested | OPEN |
| O-012 | Documents | Retention/access policy for invoices, contracts, and payment evidence? | Restricted access; no deletion schedule assumed | OPEN |
| O-013 | Delivery | Which channels may send official invoices to customers, and who authorizes? | No automatic customer delivery | OPEN |

## Qualified finance/tax review

Before production, obtain non-secret confirmation for:

- legal issuer list and PKP/PPN status;
- chart of accounts and opening balances;
- invoice/faktur numbering and tax treatment;
- revenue recognition, withholding, and correction/reversal practices;
- bank/account ownership and reconciliation responsibilities;
- retention and reporting obligations.

## Technical owner inputs later

- Private deployment target/capacity.
- Backup target and restore operator.
- Domain/private access decision.
- ERP service account provisioning entered locally, never in chat.
- No coding-agent authentication decision is open; Bos designated Hermes as sole source writer.
