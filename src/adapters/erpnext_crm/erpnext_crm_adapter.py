"""ERPNext CRM adapter — provider-neutral CRM port implementation (CRM-001).

Implements the `CrmPort` contract against the isolated ERPNext pilot
(EVAL-002) over HTTP REST only. Unit-private isolation is enforced
client-side fail-closed:

- Every method requires the caller's actor to be assigned to the active
  unit AND the active unit to be inside the adapter's authorized scope.
  Empty scope is fail-closed.
- Scope is mapped to the ERPNext `company` field (Lead, Quotation).
- Cross-unit reads raise `CrmNotFound` — existence never leaks.
- Search cursors are opaque, scope-bound, and validated server-side
  against the caller's unit.
- Conflict checks never reveal cross-unit existence (no
  CONFLICT_OTHER_UNIT verdict exists in the port).

Ownership transfer uses custom fields on Lead:
- `custom_owner_actor_ref` (Data) — controlling sales actor ref
- `custom_contact_channel` / `custom_contact_handle` (Data) — opaque
  contact identity used for in-scope conflict detection
- `custom_archived` (Check) — archive flag (Lead.status stays native)

The seeder `_seeder.py` ensures these custom fields plus the UNIT-PR1ME
company exist idempotently. NEVER deletes, never touches live data.
"""
from __future__ import annotations

import base64
import itertools
import json
from typing import Any

from src.adapters.erpnext import ErpNextAdapter, ErpNextConfig
from src.contracts.erp_port import DocumentRejected, UncertainOutcome
from src.crm.port import (
    ConflictVerdict,
    CrmDenied,
    CrmIdentity,
    CrmNotFound,
    CrmQuery,
    CrmQueryPage,
    ExportRequest,
    ExportResult,
    LeadCommand,
    LeadRecord,
    QuotationCommand,
    QuotationRecord,
)


class ErpNextCrmAdapter:
    """ERPNext implementation of the provider-neutral CRM port."""

    def __init__(
        self,
        config: ErpNextConfig,
        authorized_scope: frozenset[str],
        assignments: dict[str, frozenset[str]],
    ) -> None:
        self._inner = ErpNextAdapter(config, authorized_scope)
        self._scope = authorized_scope
        # Roster kept by reference so revocation/expiry is visible immediately.
        self._assignments = assignments
        self._seq = itertools.count(1)

    # -- guards ---------------------------------------------------------------

    def _require_assigned(self, identity: CrmIdentity) -> None:
        """Fail-closed: non-empty scope + actor assigned to the active unit."""
        if not self._scope:
            raise CrmDenied("Authorized scope is empty; CRM access is fail-closed")
        if identity.operating_unit_ref not in self._scope:
            raise CrmDenied(
                f"Unit {identity.operating_unit_ref} not in authorized scope"
            )
        units = self._assignments.get(identity.actor_ref, frozenset())
        if identity.operating_unit_ref not in units:
            raise CrmDenied(
                f"Actor {identity.actor_ref} not assigned to {identity.operating_unit_ref}"
            )

    # -- HTTP pass-through (fail-closed error mapping) -------------------------

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._inner._get(path, params=params)

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._inner._post(path, data=data)

    def _put(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._inner._put(path, data=data)

    # -- lead helpers ----------------------------------------------------------

    def _get_lead_doc(self, reference: str) -> dict[str, Any]:
        try:
            payload = self._get(f"/api/resource/Lead/{reference}")
        except DocumentRejected as e:
            raise CrmNotFound(f"Lead {reference} not found") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Lead read uncertain: {e}") from e
        return payload.get("data", {})

    def _lead_in_scope_doc(self, identity: CrmIdentity, reference: str) -> dict[str, Any]:
        doc = self._get_lead_doc(reference)
        if doc.get("company") != identity.operating_unit_ref:
            raise CrmNotFound(f"Lead {reference} not found")
        return doc

    @staticmethod
    def _map_quotation_status(native: str, docstatus: int) -> str:
        """Map ERPNext Quotation status to the contract vocabulary fail-closed.

        Contract: DRAFT | SENT | ACCEPTED | DECLINED | EXPIRED.
        docstatus 0 → always DRAFT regardless of label.
        Unknown labels fail closed to EXPIRED (never emitted verbatim).
        """
        if docstatus == 0:
            return "DRAFT"
        return {
            "OPEN": "SENT",
            "ORDERED": "ACCEPTED",
            "LOST": "DECLINED",
            "EXPIRED": "EXPIRED",
            "CANCELLED": "DECLINED",
            "PARTIALLY ORDERED": "SENT",
        }.get(native.upper(), "EXPIRED")

    @staticmethod
    def _map_lead_status(native: str, archived: bool) -> str:
        if archived:
            return "ARCHIVED"
        # Native ERPNext Lead statuses → contract statuses.
        return {
            "LEAD": "NEW",
            "OPEN": "NEW",
            "REPLIED": "QUALIFIED",
            "OPPORTUNITY": "QUALIFIED",
            "QUOTATION": "QUALIFIED",
            "CONVERTED": "CONVERTED",
            "DO NOT DISTURB": "ARCHIVED",
            "INTERESTED": "QUALIFIED",
        }.get(native.upper(), "NEW")

    @staticmethod
    def _lead_doc_to_record(doc: dict[str, Any]) -> LeadRecord:
        archived = bool(doc.get("custom_archived"))
        status = ErpNextCrmAdapter._map_lead_status(str(doc.get("status") or "Lead"), archived)
        return LeadRecord(
            reference=str(doc.get("name")),
            operating_unit_ref=str(doc.get("company", "")),
            display_name=str(doc.get("lead_name", "")),
            contact_channel=str(doc.get("custom_contact_channel", "")),
            contact_handle=str(doc.get("custom_contact_handle", "")),
            source=str(doc.get("source", "")),
            status=status,
            owner_actor_ref=str(doc.get("custom_owner_actor_ref", "")),
            payload={},
        )

    # -- leads ------------------------------------------------------------------

    def create_lead(self, command: LeadCommand) -> str:
        self._require_assigned(command.identity)
        data = {
            "lead_name": command.display_name,
            "company": command.identity.operating_unit_ref,
            "source": command.source,
            "status": "Lead",
            "custom_owner_actor_ref": command.identity.actor_ref,
            "custom_contact_channel": command.contact_channel,
            "custom_contact_handle": command.contact_handle,
        }
        try:
            payload = self._post("/api/resource/Lead", data)
        except DocumentRejected as e:
            raise CrmDenied(f"Lead create rejected: {e}") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Lead create uncertain: {e}") from e
        return str(payload.get("data", {}).get("name"))

    def read_lead(self, identity: CrmIdentity, reference: str) -> LeadRecord:
        self._require_assigned(identity)
        doc = self._lead_in_scope_doc(identity, reference)
        return self._lead_doc_to_record(doc)

    def transfer_lead(
        self,
        identity: CrmIdentity,
        reference: str,
        *,
        new_owner_actor_ref: str,
        new_unit_ref: str | None = None,
    ) -> None:
        self._require_assigned(identity)
        doc = self._lead_in_scope_doc(identity, reference)
        target_unit = new_unit_ref or doc.get("company")
        # New owner must be assigned to the target unit (fail-closed).
        if target_unit not in self._assignments.get(new_owner_actor_ref, frozenset()):
            raise CrmDenied(
                f"Actor {new_owner_actor_ref} not assigned to {target_unit}"
            )
        # Target unit must stay within authorized scope (no escape).
        if target_unit not in self._scope:
            raise CrmDenied(f"Target unit {target_unit} not in authorized scope")
        update = {
            "custom_owner_actor_ref": new_owner_actor_ref,
            "company": target_unit,
        }
        try:
            self._put(f"/api/resource/Lead/{reference}", update)
        except DocumentRejected as e:
            raise CrmDenied(f"Lead transfer rejected: {e}") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Lead transfer uncertain: {e}") from e

    def archive_lead(self, identity: CrmIdentity, reference: str) -> None:
        self._require_assigned(identity)
        self._lead_in_scope_doc(identity, reference)
        try:
            self._put(f"/api/resource/Lead/{reference}", {"custom_archived": 1})
        except DocumentRejected as e:
            raise CrmDenied(f"Lead archive rejected: {e}") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Lead archive uncertain: {e}") from e

    # -- quotations ---------------------------------------------------------------

    def create_quotation(self, command: QuotationCommand) -> str:
        self._require_assigned(command.identity)
        # Referential integrity within the active unit: cross-unit lead refs
        # are neither usable nor revealed.
        self._lead_in_scope_doc(command.identity, command.lead_ref)
        data = {
            "doctype": "Quotation",
            "quotation_to": "Lead",
            "party_name": command.lead_ref,
            "company": command.identity.operating_unit_ref,
            "customer_name": command.customer_ref,
            "currency": command.currency,
            "valid_till": command.valid_until,
            "custom_crm_total_amount": command.total_amount,
            "custom_crm_customer_ref": command.customer_ref,
            "items": [
                {
                    "item_code": "SVC-ADS",
                    "qty": 1,
                    "rate": command.total_amount,
                }
            ],
        }
        try:
            payload = self._post("/api/resource/Quotation", data)
        except DocumentRejected as e:
            raise CrmDenied(f"Quotation create rejected: {e}") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Quotation create uncertain: {e}") from e
        return str(payload.get("data", {}).get("name"))

    def read_quotation(
        self, identity: CrmIdentity, reference: str
    ) -> QuotationRecord:
        self._require_assigned(identity)
        try:
            payload = self._get(f"/api/resource/Quotation/{reference}")
        except DocumentRejected as e:
            raise CrmNotFound(f"Quotation {reference} not found") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Quotation read uncertain: {e}") from e
        doc = payload.get("data", {})
        if doc.get("company") != identity.operating_unit_ref:
            raise CrmNotFound(f"Quotation {reference} not found")
        status = self._map_quotation_status(
            str(doc.get("status") or "Draft"), int(doc.get("docstatus", 0))
        )
        total = doc.get("custom_crm_total_amount") or doc.get("grand_total") or "0"
        customer_ref = doc.get("custom_crm_customer_ref") or str(
            doc.get("customer_name", "")
        )
        return QuotationRecord(
            reference=str(doc.get("name")),
            operating_unit_ref=str(doc.get("company", "")),
            lead_ref=str(doc.get("party_name", "")),
            customer_ref=str(customer_ref),
            total_amount=str(total),
            currency=str(doc.get("currency", "")),
            status=status,
            valid_until=str(doc.get("valid_till", "")),
            payload={},
        )

    # -- search / query --------------------------------------------------------

    def _search(
        self,
        kind: str,
        doctype: str,
        ref_field: str,
        query: CrmQuery,
    ) -> CrmQueryPage:
        self._require_assigned(query.identity)
        if query.limit < 1:
            raise CrmDenied(f"Search limit must be >= 1, got {query.limit}")

        filters: list[list[Any]] = [
            [doctype, "company", "=", query.identity.operating_unit_ref]
        ]
        if query.status:
            if doctype == "Lead":
                if query.status == "ARCHIVED":
                    filters.append([doctype, "custom_archived", "=", 1])
                else:
                    native = {
                        "NEW": "Lead",
                        "QUALIFIED": "Qualified",
                        "CONVERTED": "Converted",
                    }.get(query.status)
                    if native is None:
                        raise CrmDenied(f"Unsupported lead status filter: {query.status}")
                    filters.append([doctype, "status", "=", native])
                    # Contract-NEW must exclude archived leads (F-001).
                    filters.append([doctype, "custom_archived", "!=", 1])
            elif doctype == "Quotation":
                qmap = {
                    "DRAFT": "Draft",
                    "SENT": "Open",
                    "ACCEPTED": "Ordered",
                    "DECLINED": "Lost",
                    "EXPIRED": "Expired",
                }
                native = qmap.get(query.status)
                if native is None:
                    raise CrmDenied(
                        f"Unsupported quotation status filter: {query.status}"
                    )
                filters.append([doctype, "status", "=", native])
        if query.text:
            filters.append([doctype, ref_field, "like", f"%{query.text}%"])

        offset = 0
        if query.cursor is not None:
            try:
                decoded = base64.urlsafe_b64decode(query.cursor.encode()).decode()
                cursor_unit, sep, raw = decoded.partition(":")
            except Exception as e:
                raise CrmDenied("Cursor is malformed or belongs to another scope") from e
            if (
                cursor_unit != query.identity.operating_unit_ref
                or not sep
                or not raw.isdigit()
            ):
                raise CrmDenied("Cursor is malformed or belongs to another scope")
            offset = int(raw)

        params = {
            "fields": json.dumps(["name"]),
            "filters": json.dumps(filters),
            "limit_page_length": str(query.limit + 1),  # fetch one extra for next_cursor
            "limit_start": str(offset),
            "order_by": "name asc",
        }
        try:
            payload = self._get(f"/api/resource/{doctype}", params=params)
        except DocumentRejected as e:
            raise CrmDenied(f"Search rejected: {e}") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Search uncertain: {e}") from e
        docs = payload.get("data", [])
        page_docs = docs[: query.limit]
        next_cursor = None
        if len(docs) > query.limit:
            next_cursor = base64.urlsafe_b64encode(
                f"{query.identity.operating_unit_ref}:{offset + query.limit}".encode()
            ).decode()

        # total (scope-bounded COUNT)
        try:
            count_payload = self._post(
                "/api/method/frappe.client.get_count",
                {"doctype": doctype, "filters": filters},
            )
            total = int(count_payload.get("message", len(docs)))
        except (DocumentRejected, UncertainOutcome):
            total = offset + len(docs)

        return CrmQueryPage(
            kind=kind,
            references=tuple(str(d.get("name")) for d in page_docs),
            scoped=True,
            total=total,
            next_cursor=next_cursor,
        )

    def search_leads(self, query: CrmQuery) -> CrmQueryPage:
        return self._search("LEAD", "Lead", "lead_name", query)

    def query_quotations(self, query: CrmQuery) -> CrmQueryPage:
        return self._search("QUOTATION", "Quotation", "customer_name", query)

    # -- export -----------------------------------------------------------------

    def export(self, request: ExportRequest) -> ExportResult:
        self._require_assigned(request.identity)
        if request.kind != "LEAD":
            raise CrmDenied(f"Export kind {request.kind} not supported")
        if request.max_rows < 1:
            raise CrmDenied(f"Export max_rows must be >= 1, got {request.max_rows}")
        filters = [["Lead", "company", "=", request.identity.operating_unit_ref]]
        params = {
            "fields": json.dumps(
                ["name", "lead_name", "status", "custom_archived"]
            ),
            "filters": json.dumps(filters),
            "limit_page_length": str(request.max_rows),
            "order_by": "name asc",
        }
        try:
            payload = self._get("/api/resource/Lead", params=params)
        except DocumentRejected as e:
            raise CrmDenied(f"Export rejected: {e}") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Export uncertain: {e}") from e
        rows = []
        for doc in payload.get("data", [])[: request.max_rows]:
            archived = bool(doc.get("custom_archived"))
            status = self._map_lead_status(str(doc.get("status") or "Lead"), archived)
            rows.append(
                {
                    "reference": str(doc.get("name")),
                    "display_name": str(doc.get("lead_name", "")),
                    "status": status,
                }
            )
        return ExportResult(
            evidence_ref=request.evidence_ref,
            operating_unit_ref=request.identity.operating_unit_ref,
            row_count=len(rows),
            rows=tuple(rows),
        )

    # -- conflict check ---------------------------------------------------------

    def check_customer_conflict(
        self, identity: CrmIdentity, contact_channel: str, contact_handle: str
    ) -> ConflictVerdict:
        self._require_assigned(identity)
        filters = [
            ["Lead", "company", "=", identity.operating_unit_ref],
            ["Lead", "custom_contact_channel", "=", contact_channel],
            ["Lead", "custom_contact_handle", "=", contact_handle],
        ]
        params = {
            "fields": json.dumps(["name"]),
            "filters": json.dumps(filters),
            "limit_page_length": "1",
        }
        try:
            payload = self._get("/api/resource/Lead", params=params)
        except DocumentRejected as e:
            raise CrmDenied(f"Conflict check rejected: {e}") from e
        except UncertainOutcome as e:
            raise CrmDenied(f"Conflict check uncertain: {e}") from e
        if payload.get("data"):
            return ConflictVerdict.CONFLICT_IN_SCOPE
        return ConflictVerdict.CLEAR
