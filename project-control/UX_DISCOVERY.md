# UX Discovery — ERP Kreasi Hebat

- Status: `DRAFT`
- Languages: Indonesian-first; technical identifiers remain stable English codes internally.

## Users and context

### Chat users
Sales, operations, and finance users work primarily from mobile WhatsApp/Telegram groups. They need short prompts, clear missing-field questions, previews, and safe recovery. Connectivity may be intermittent and messages may be retried.

### ERP/dashboard users
Finance reviewers, PT tax/finance, owner/controller, and administrators use desktop or mobile web for review, reconciliation, configuration, reports, and audit.

### Sensitivity
Lead ownership, customer identity, pricing, finance, bank destinations, payment evidence, HR, and tax data have different visibility. Shared office/group membership is not sufficient authorization.

## Primary outcomes

- Sales prepares a complete quotation/invoice request without navigating complex ERP forms.
- Finance sees exactly what will be issued, under which legal identity/tax/account, before posting.
- Owner can view authorized roll-ups while unit sales remain isolated.
- Users can understand why an action is blocked and what safe next step is required.

## Journey inventory

1. Create draft invoice from chat.
2. Review and post in chat or ERP UI according to role.
3. View/download safe invoice PDF.
4. Record partial/full payment with evidence.
5. Investigate overdue receivable.
6. Resolve cross-unit lead conflict through controller workflow.
7. Configure/onboard a unit (admin only).
8. Recover from ERP/channel timeout without duplicate mutation.

## Required state inventory

- Initial/idle
- Resolving identity/scope
- Missing required fields
- Ambiguous unit/issuer/tax/account
- Permission denied without information leak
- Preview ready
- Changed/stale preview
- Posting in progress
- Posted and verified
- ERP succeeded but response uncertain (`reconciliation required`)
- Delivery failed after successful posting
- Duplicate retry returning existing result
- Empty list/report
- Offline/channel retry
- Evidence rejected (type/size/duplicate/inaccessible)
- Cancel/reversal confirmation and result

## Constraints

- Mobile chat messages should be concise and scannable.
- No fake AI progress, invented invoice number, or unverified “success.”
- Account display uses approved alias/masked label, never full number in general group.
- PPN and legal issuer are explicit in preview.
- Destructive/reversal actions use supported ERP semantics and clear consequence copy.
- Dashboard must work at compact and wide viewports without horizontal overflow.

## Existing system observation

There is no application UI yet; only project-control documents exist. Therefore this discovery defines the first UX contract rather than modifying an established design system. The adopted ERP's native components/tokens should be reused before creating a custom visual language.

## Evidence required later

- Chat transcript fixtures for success, missing data, denied, duplicate retry, and uncertain mutation.
- Browser/E2E evidence at compact and wide viewports.
- Keyboard/focus path for review, approval/post, dialog cancel, and evidence upload.
- Semantic/accessibility assertions and non-color-only statuses.
- Screenshots containing synthetic data only.
