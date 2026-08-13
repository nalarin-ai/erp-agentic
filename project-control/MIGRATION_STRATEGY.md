# Data Migration and Reconciliation Strategy

- Status: `DRAFT_BLOCKED_SOURCE_DISCOVERY`
- No live workbook/data import is authorized by this document.

## Objectives

Move only validated business records into the adopted ERP while preserving unit, sales owner, legal issuer, tax/account identity, dates, currency, balances, evidence references, and source traceability.

## Source discovery

For each workbook/system, record without exposing live values:

- owner and authoritative status;
- sheets/tables, columns, types, row count, date/currency conventions;
- unit/legal issuer represented;
- customer/vendor identifiers and duplicate quality;
- invoice/payment/opening balance semantics;
- attachment/evidence location;
- formulas vs stored values;
- known missing/inconsistent fields.

## Pipeline

```text
Read-only source copy
 -> checksum and inventory
 -> sanitized schema profile
 -> staging import
 -> validation/mapping
 -> duplicate/conflict report
 -> dry-run totals and row errors
 -> bounded synthetic/trial batch
 -> reconciliation
 -> approved production batch (later gate)
```

## Mandatory validation

- unit and sales scope;
- legal issuer and tax profile;
- allowed account alias;
- unique source/external reference;
- dates, currency, decimal amounts;
- customer identity/mapping;
- invoice/payment relationship and open balance;
- required evidence/reference;
- no unsupported formula/error values;
- no secret columns imported to general tables/logs.

## Reconciliation

Compare source/staging/ERP:

- row/document counts by unit, issuer, type, status;
- subtotal/tax/total/open amount by currency;
- payment totals and receivable aging;
- rejected/duplicate rows with reasons;
- sample document line/evidence/audit correctness;
- opening balances under qualified accounting review.

## Rollback

Dry-run performs zero ERP writes. Trial batches use isolated environment and stable external references. Production rollback must use ERP-supported cancellation/reversal or restore decision; never hard-delete financial records to hide an import error.

## Privacy and safety

Use synthetic or redacted samples during development. Real source copies remain access-controlled. Logs/reports use aliases and aggregates. No workbook containing banking credentials, passwords, tokens, full card data, or unrelated personal data enters the repository.
