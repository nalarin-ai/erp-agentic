"""In-memory fixture CRM adapter (CRM-001).

Network-disabled, deterministic implementation of the CrmPort contract used
by unit tests. All state is in-memory; scope checks are fail-closed.
"""
from __future__ import annotations

import itertools
from typing import Any

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


class FixtureCrmAdapter:
    """Deterministic in-memory CrmPort implementation."""

    def __init__(self, assignments: dict[str, frozenset[str]]):
        """assignments: actor_ref -> set of unit refs the actor is assigned to.

        The roster mapping is kept by reference (not copied) so revocation
        and expiry are visible immediately to every subsequent call.
        """
        self._assignments = assignments
        self._leads: dict[str, LeadRecord] = {}
        self._quotations: dict[str, QuotationRecord] = {}
        self._seq = itertools.count(1)
        self._transfers: list[tuple[str, str, str]] = []  # (ref, actor, unit)

    # -- guards ---------------------------------------------------------------

    def _require_assigned(self, identity: CrmIdentity) -> None:
        """Fail-closed: actor must be assigned to the active unit.

        Assignments are read live from the roster mapping at call time, so
        revocation/expiry takes effect immediately (no stale cache).
        """
        units = self._assignments.get(identity.actor_ref, frozenset())
        if identity.operating_unit_ref not in units:
            raise CrmDenied(
                f"Actor {identity.actor_ref} not assigned to {identity.operating_unit_ref}"
            )

    def _lead_in_scope(self, identity: CrmIdentity, reference: str) -> LeadRecord:
        record = self._leads.get(reference)
        if record is None or record.operating_unit_ref != identity.operating_unit_ref:
            # Fail-closed: cross-unit existence is indistinguishable from absence.
            raise CrmNotFound(f"Lead {reference} not found")
        return record

    # -- leads ----------------------------------------------------------------

    def create_lead(self, command: LeadCommand) -> str:
        self._require_assigned(command.identity)
        ref = f"LEAD-{next(self._seq):04d}"
        self._leads[ref] = LeadRecord(
            reference=ref,
            operating_unit_ref=command.identity.operating_unit_ref,
            display_name=command.display_name,
            contact_channel=command.contact_channel,
            contact_handle=command.contact_handle,
            source=command.source,
            status="NEW",
            owner_actor_ref=command.identity.actor_ref,
            payload={},
        )
        return ref

    def read_lead(self, identity: CrmIdentity, reference: str) -> LeadRecord:
        self._require_assigned(identity)
        return self._lead_in_scope(identity, reference)

    def transfer_lead(
        self,
        identity: CrmIdentity,
        reference: str,
        *,
        new_owner_actor_ref: str,
        new_unit_ref: str | None = None,
    ) -> None:
        self._require_assigned(identity)
        record = self._lead_in_scope(identity, reference)
        target_unit = new_unit_ref or record.operating_unit_ref
        # New owner must be assigned to the target unit.
        if target_unit not in self._assignments.get(new_owner_actor_ref, frozenset()):
            raise CrmDenied(
                f"Actor {new_owner_actor_ref} not assigned to {target_unit}"
            )
        self._leads[reference] = LeadRecord(
            reference=record.reference,
            operating_unit_ref=target_unit,
            display_name=record.display_name,
            contact_channel=record.contact_channel,
            contact_handle=record.contact_handle,
            source=record.source,
            status=record.status,
            owner_actor_ref=new_owner_actor_ref,
            payload=record.payload,
        )
        self._transfers.append((reference, new_owner_actor_ref, target_unit))

    def archive_lead(self, identity: CrmIdentity, reference: str) -> None:
        self._require_assigned(identity)
        record = self._lead_in_scope(identity, reference)
        self._leads[reference] = LeadRecord(
            reference=record.reference,
            operating_unit_ref=record.operating_unit_ref,
            display_name=record.display_name,
            contact_channel=record.contact_channel,
            contact_handle=record.contact_handle,
            source=record.source,
            status="ARCHIVED",
            owner_actor_ref=record.owner_actor_ref,
            payload=record.payload,
        )

    # -- quotations -------------------------------------------------------------

    def create_quotation(self, command: QuotationCommand) -> str:
        self._require_assigned(command.identity)
        # Referential integrity within the active unit: the referenced lead
        # must exist inside the caller's unit scope (cross-unit existence is
        # neither usable nor revealed).
        lead = self._leads.get(command.lead_ref)
        if lead is None or lead.operating_unit_ref != command.identity.operating_unit_ref:
            raise CrmNotFound(
                f"Lead {command.lead_ref} not found in {command.identity.operating_unit_ref}"
            )
        ref = f"QUO-{next(self._seq):04d}"
        self._quotations[ref] = QuotationRecord(
            reference=ref,
            operating_unit_ref=command.identity.operating_unit_ref,
            lead_ref=command.lead_ref,
            customer_ref=command.customer_ref,
            total_amount=command.total_amount,
            currency=command.currency,
            status="DRAFT",
            valid_until=command.valid_until,
            payload={},
        )
        return ref

    def read_quotation(
        self, identity: CrmIdentity, reference: str
    ) -> QuotationRecord:
        self._require_assigned(identity)
        record = self._quotations.get(reference)
        if record is None or record.operating_unit_ref != identity.operating_unit_ref:
            raise CrmNotFound(f"Quotation {reference} not found")
        return record

    # -- search / query ---------------------------------------------------------

    def _search(
        self, kind: str, store: dict[str, Any], query: CrmQuery
    ) -> CrmQueryPage:
        self._require_assigned(query.identity)
        if query.limit < 1:
            raise CrmDenied(f"Search limit must be >= 1, got {query.limit}")
        items = [
            rec
            for rec in store.values()
            if rec.operating_unit_ref == query.identity.operating_unit_ref
        ]
        if query.status:
            items = [rec for rec in items if rec.status == query.status]
        if query.text:
            needle = query.text.casefold()
            items = [
                rec for rec in items if needle in getattr(rec, "display_name", "").casefold()
            ]
        # Cursor handling: cursor encodes (unit, offset); scope-bound and
        # fail-closed on malformed input (never a raw ValueError).
        offset = 0
        if query.cursor is not None:
            cursor_unit, sep, raw = query.cursor.partition(":")
            if (
                cursor_unit != query.identity.operating_unit_ref
                or not sep
                or not raw.isdigit()
            ):
                raise CrmDenied("Cursor is malformed or belongs to another scope")
            offset = int(raw)
        page = items[offset: offset + query.limit]
        next_cursor = None
        if offset + query.limit < len(items):
            next_cursor = f"{query.identity.operating_unit_ref}:{offset + query.limit}"
        return CrmQueryPage(
            kind=kind,
            references=tuple(rec.reference for rec in page),
            scoped=True,
            total=len(items),
            next_cursor=next_cursor,
        )

    def search_leads(self, query: CrmQuery) -> CrmQueryPage:
        return self._search("LEAD", self._leads, query)

    def query_quotations(self, query: CrmQuery) -> CrmQueryPage:
        return self._search("QUOTATION", self._quotations, query)

    # -- export -----------------------------------------------------------------

    def export(self, request: ExportRequest) -> ExportResult:
        self._require_assigned(request.identity)
        if request.kind != "LEAD":
            raise CrmDenied(f"Export kind {request.kind} not supported by fixture")
        if request.max_rows < 1:
            raise CrmDenied(f"Export max_rows must be >= 1, got {request.max_rows}")
        rows = []
        for rec in self._leads.values():
            if rec.operating_unit_ref != request.identity.operating_unit_ref:
                continue
            if len(rows) >= request.max_rows:
                break
            rows.append(
                {
                    "reference": rec.reference,
                    "display_name": rec.display_name,
                    "status": rec.status,
                }
            )
        return ExportResult(
            evidence_ref=request.evidence_ref,
            operating_unit_ref=request.identity.operating_unit_ref,
            row_count=len(rows),
            rows=tuple(rows),
        )

    # -- conflict check -----------------------------------------------------------

    def check_customer_conflict(
        self, identity: CrmIdentity, contact_channel: str, contact_handle: str
    ) -> ConflictVerdict:
        self._require_assigned(identity)
        for rec in self._leads.values():
            if (
                rec.operating_unit_ref == identity.operating_unit_ref
                and rec.contact_channel == contact_channel
                and rec.contact_handle == contact_handle
            ):
                return ConflictVerdict.CONFLICT_IN_SCOPE
        return ConflictVerdict.CLEAR
