# Native ERP Isolation Test Surface

Single-site adoption is conditional on fail-closed isolation evidence across every native surface. Gateway-only isolation is insufficient.

## Surfaces to test with direct unit-sales credentials

- ERP web lists/forms and direct document URLs.
- REST/RPC/API endpoints and bulk query methods.
- Global search, autocomplete, link fields, counts, filters, and timing/error behavior.
- Reports, dashboards, exports, print/PDF, email/notification previews.
- Attachments/private files and generated documents.
- Background jobs, assignments, comments, mentions, activity feeds, and subscriptions.
- Import tools, data export, list view bulk actions, mobile views, cached pages.
- Delegated/admin roles and permission configuration changes.

## Required negative matrix

For Banyumedia, Pr1me, Contractor, Heavy Equipment, PT finance, owner, unknown/deactivated user:

- cannot enumerate protected records/counts;
- cannot access by guessed ID/direct URL;
- cannot infer customer existence through autocomplete/error/timing beyond accepted threat model;
- cannot export/print/download protected attachments;
- cannot receive cross-unit notifications;
- cannot mutate ownership/unit/issuer to escape scope;
- owner/controller roll-up is explicit and auditable.

## Decision rule

- If all relevant surfaces enforce required isolation, single-site remains eligible.
- If unavoidable native surfaces leak data or permissions cannot be expressed safely, use separate ERP sites/tenants or remove direct native access for affected roles behind a proven gateway.
- The decision is an ADR backed by raw tests at a pinned ERP version; documentation claims are insufficient.
