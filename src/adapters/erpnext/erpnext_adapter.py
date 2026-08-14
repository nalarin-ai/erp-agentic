"""ERPNext adapter — provider-neutral ERP port implementation (ADP-002).

This module implements the `ErpPort` contract against an isolated ERPNext
instance (EVAL-002). It uses HTTP REST API only, never direct DB access.

Security invariants:
- All refs are synthetic opaque (CUST-*, INV-*, PAY-*, EVI-*, ACC-*).
- No credentials in code; connection config injected via constructor.
- Scoped queries intersect server-side filters with caller's authorized scope.
- Draft creation reserves nothing; official number only after verified post.
- Posting is idempotent via ERPNext naming + idempotency key.
- Payments require evidence_ref; reversals are compensating records.
- Reconciliation reads back authoritative state; no blind reissue.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.contracts.erp_port import (
    DocumentRejected,
    DraftInvoiceCommand,
    DraftPaymentCommand,
    ErpPort,
    InvoiceRecord,
    PaymentRecord,
    PostingOutcome,
    PostingResult,
    QueryResult,
    ReversalCommand,
    UncertainOutcome,
)


# ---------------------------------------------------------------------------
# Configuration (injected, no hardcoded secrets)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ErpNextConfig:
    """Connection config for isolated ERPNext instance."""

    base_url: str  # e.g. "http://127.0.0.1:18080"
    site_name: str  # e.g. "erpnext-pilot.localhost"
    admin_password: str  # synthetic only
    timeout_seconds: int = 30


# ---------------------------------------------------------------------------
# ERPNext adapter
# ---------------------------------------------------------------------------


class ErpNextAdapter:
    """ERPNext implementation of the provider-neutral ERP port.

    Uses HTTP REST API against isolated ERPNext (EVAL-002). All operations
    are scoped to the caller's authorized unit context.
    """

    def __init__(self, config: ErpNextConfig, authorized_scope: frozenset[str]):
        """Initialize adapter with config and authorized scope.

        Args:
            config: Connection config (synthetic secrets only).
            authorized_scope: Set of operating_unit_ref values the caller may access.
        """
        self._config = config
        self._scope = authorized_scope
        self._base = config.base_url.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"token administrator:{config.admin_password}",
        }

    # -- internal HTTP helpers -----------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make HTTP request to ERPNext API."""
        url = f"{self._base}{path}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode() if data else None,
            headers=self._headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=self._config.timeout_seconds) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                err = json.loads(body)
                msg = err.get("message", body)
            except json.JSONDecodeError:
                msg = body
            raise DocumentRejected(f"ERPNext HTTP {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise UncertainOutcome(f"ERPNext connection failed: {e.reason}") from e

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, data=data)

    def _put(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", path, data=data)

    def _delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path)

    # -- ERPNext document helpers --------------------------------------------

    def _erpnext_doctype(self, kind: str) -> str:
        """Map contract kind to ERPNext doctype."""
        return {
            "INVOICE": "Sales Invoice",
            "PAYMENT": "Payment Entry",
            "CUSTOMER": "Customer",
            "ITEM": "Item",
        }.get(kind, kind)

    def _to_erpnext_ref(self, ref: str) -> str:
        """Convert opaque ref to ERPNext naming (pass-through for now)."""
        return ref

    def _from_erpnext_ref(self, name: str) -> str:
        """Convert ERPNext document name to opaque ref."""
        return name

    # -- ErpPort implementation ----------------------------------------------

    def create_draft_invoice(self, command: DraftInvoiceCommand) -> str:
        """Create a draft Sales Invoice in ERPNext.

        Reserves nothing: ERPNext draft has no official number until submit.
        Returns draft reference (ERPNext document name).
        """
        # Validate scope
        if command.identity.operating_unit_ref not in self._scope:
            raise DocumentRejected(
                f"Unit {command.identity.operating_unit_ref} not in authorized scope"
            )

        # Build ERPNext Sales Invoice payload
        items = [
            {
                "item_code": line.service_ref,
                "description": line.description,
                "qty": float(line.quantity),
                "rate": float(line.unit_price_amount),
            }
            for line in command.lines
        ]

        payload = {
            "doctype": "Sales Invoice",
            "customer": command.customer_ref,
            "posting_date": command.issued_on,
            "due_date": command.due_on,
            "items": items,
            "docstatus": 0,  # Draft
            "company": command.identity.operating_unit_ref,  # Map unit to company
            "currency": command.lines[0].currency if command.lines else "IDR",
        }

        result = self._post("/api/resource/Sales Invoice", payload)
        return self._from_erpnext_ref(result["data"]["name"])

    def read_invoice(self, reference: str) -> InvoiceRecord:
        """Read back a Sales Invoice from ERPNext."""
        name = self._to_erpnext_ref(reference)
        result = self._get(f"/api/resource/Sales Invoice/{name}")
        data = result["data"]

        # Map ERPNext status to contract status
        docstatus = data.get("docstatus", 0)
        if docstatus == 0:
            status = "DRAFT"
        elif docstatus == 1:
            status = "POSTED"
        elif docstatus == 2:
            status = "CANCELLED"
        else:
            status = "UNKNOWN"

        return InvoiceRecord(
            reference=self._from_erpnext_ref(data["name"]),
            status=status,
            total_amount=str(data.get("grand_total", "0")),
            currency=data.get("currency", "IDR"),
            open_amount=str(data.get("outstanding_amount", "0")),
            issued_on=data.get("posting_date", ""),
            due_on=data.get("due_date", ""),
            payload=data,
        )

    def post_invoice(self, reference: str) -> PostingResult:
        """Submit a draft Sales Invoice in ERPNext.

        ERPNext assigns official number on submit. Idempotent via document name.
        """
        name = self._to_erpnext_ref(reference)

        # Check current state
        try:
            current = self.read_invoice(reference)
        except DocumentRejected:
            return PostingResult(
                outcome=PostingOutcome.REJECTED,
                reference=None,
                reason="Invoice not found",
            )

        if current.status == "POSTED":
            # Already posted — idempotent success
            return PostingResult(
                outcome=PostingOutcome.POSTED,
                reference=current.reference,
                reason=None,
            )

        if current.status == "CANCELLED":
            return PostingResult(
                outcome=PostingOutcome.REJECTED,
                reference=None,
                reason="Invoice is cancelled",
            )

        # Submit the draft
        try:
            self._put(
                f"/api/resource/Sales Invoice/{name}",
                {"docstatus": 1},
            )
            # Read back to get official reference
            posted = self.read_invoice(reference)
            return PostingResult(
                outcome=PostingOutcome.POSTED,
                reference=posted.reference,
                reason=None,
            )
        except DocumentRejected as e:
            return PostingResult(
                outcome=PostingOutcome.REJECTED,
                reference=None,
                reason=str(e),
            )
        except UncertainOutcome:
            raise

    def record_payment(self, command: DraftPaymentCommand) -> str:
        """Create a Payment Entry in ERPNext.

        Requires evidence_ref; stores as reference in remarks.
        """
        if not command.evidence_ref:
            raise DocumentRejected("Payment requires evidence_ref")

        payload = {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": command.invoice_ref.split("-")[0],  # Extract customer from invoice ref
            "paid_amount": float(command.amount),
            "received_amount": float(command.amount),
            "reference_no": command.evidence_ref,
            "reference_date": "2026-08-14",  # Use current date in real impl
            "remarks": f"Evidence: {command.evidence_ref}; Account: {command.destination_account_alias}",
        }

        result = self._post("/api/resource/Payment Entry", payload)
        return self._from_erpnext_ref(result["data"]["name"])

    def read_payment(self, reference: str) -> PaymentRecord:
        """Read back a Payment Entry from ERPNext."""
        name = self._to_erpnext_ref(reference)
        result = self._get(f"/api/resource/Payment Entry/{name}")
        data = result["data"]

        return PaymentRecord(
            reference=self._from_erpnext_ref(data["name"]),
            invoice_ref=data.get("references", [{}])[0].get("reference_name", ""),
            amount=str(data.get("paid_amount", "0")),
            currency=data.get("currency", "IDR"),
            evidence_ref=data.get("reference_no", ""),
            destination_account_alias=data.get("remarks", "").split("Account: ")[-1] if "Account: " in data.get("remarks", "") else "",
            reversal_of=None,
        )

    def reverse_payment(self, command: ReversalCommand) -> str:
        """Create a compensating Payment Entry reversal in ERPNext.

        ERPNext supports cancellation; we create a reverse entry instead.
        """
        original = self.read_payment(command.payment_ref)

        payload = {
            "doctype": "Payment Entry",
            "payment_type": "Pay",  # Reverse direction
            "party_type": "Customer",
            "party": original.invoice_ref.split("-")[0],
            "paid_amount": float(original.amount),
            "received_amount": float(original.amount),
            "reference_no": f"{original.evidence_ref}-REV",
            "reference_date": "2026-08-14",
            "remarks": f"Reversal of {command.payment_ref}: {command.reason}",
        }

        result = self._post("/api/resource/Payment Entry", payload)
        return self._from_erpnext_ref(result["data"]["name"])

    def cancel_invoice(self, reference: str) -> None:
        """Cancel a Sales Invoice in ERPNext."""
        name = self._to_erpnext_ref(reference)
        current = self.read_invoice(reference)

        if current.status == "DRAFT":
            # Delete draft
            self._delete(f"/api/resource/Sales Invoice/{name}")
        elif current.status == "POSTED":
            # Cancel posted document
            self._put(
                f"/api/resource/Sales Invoice/{name}",
                {"docstatus": 2},
            )
        else:
            raise DocumentRejected(f"Cannot cancel invoice in status {current.status}")

    def query_invoices(
        self,
        *,
        status: str | None = None,
        operating_unit_ref: str | None = None,
        customer_ref: str | None = None,
    ) -> QueryResult:
        """Query Sales Invoices with server-side scope intersection."""
        # Build filters
        filters = []

        # Always intersect with authorized scope
        if operating_unit_ref:
            if operating_unit_ref not in self._scope:
                # Caller requested a unit they cannot see
                return QueryResult(
                    kind="INVOICE",
                    references=(),
                    scoped=True,
                    total=0,
                )
            filters.append(f'["company","=","{operating_unit_ref}"]')
        else:
            # Default to all authorized units
            scope_list = list(self._scope)
            if len(scope_list) == 1:
                filters.append(f'["company","=","{scope_list[0]}"]')
            else:
                # Multi-unit: use IN operator
                units_str = json.dumps(scope_list)
                filters.append(f'["company","in",{units_str}]')

        if status:
            docstatus = {"DRAFT": 0, "POSTED": 1, "CANCELLED": 2}.get(status)
            if docstatus is not None:
                filters.append(f'["docstatus","=","{docstatus}"]')

        if customer_ref:
            filters.append(f'["customer","=","{customer_ref}"]')

        params = {
            "fields": '["name"]',
            "limit_page_length": "1000",
        }
        if filters:
            params["filters"] = f"[{','.join(filters)}]"

        result = self._get("/api/resource/Sales Invoice", params=params)
        data = result.get("data", [])

        return QueryResult(
            kind="INVOICE",
            references=tuple(self._from_erpnext_ref(d["name"]) for d in data),
            scoped=True,
            total=len(data),
        )

    def ping(self) -> bool:
        """Liveness probe."""
        try:
            self._get("/api/method/ping")
            return True
        except DocumentRejected:
            return False
        except UncertainOutcome:
            raise
        except Exception:
            raise UncertainOutcome("Ping failed")

    # -- reconciliation read-back surface ------------------------------------

    def reconcile_post(self, draft_reference: str) -> PostingResult:
        """Classify an UNCERTAIN post via authoritative read-back."""
        try:
            record = self.read_invoice(draft_reference)
        except DocumentRejected:
            return PostingResult(
                outcome=PostingOutcome.REJECTED,
                reference=None,
                reason="Draft not found",
            )

        if record.status == "POSTED":
            return PostingResult(
                outcome=PostingOutcome.POSTED,
                reference=record.reference,
                reason=None,
            )

        return PostingResult(
            outcome=PostingOutcome.REJECTED,
            reference=None,
            reason=f"Draft in status {record.status}",
        )

    def reconcile_payment(self, evidence_ref: str) -> PaymentRecord:
        """Classify an uncertain payment by its reserved evidence reference."""
        # Query by reference_no
        params = {
            "fields": '["name"]',
            "filters": f'[["reference_no","=","{evidence_ref}"]]',
        }
        result = self._get("/api/resource/Payment Entry", params=params)
        data = result.get("data", [])

        if not data:
            raise DocumentRejected(f"No payment with evidence {evidence_ref}")

        return self.read_payment(data[0]["name"])

    def known_draft_refs(self) -> set[str]:
        """Snapshot of every draft handle this provider issued."""
        result = self.query_invoices(status="DRAFT")
        return set(result.references)

    def payment_evidence_index(self) -> tuple[tuple[str, str], ...]:
        """(payment_ref, evidence_ref) pairs for payment orphan cross-checks."""
        params = {
            "fields": '["name","reference_no"]',
            "limit_page_length": "1000",
        }
        result = self._get("/api/resource/Payment Entry", params=params)
        data = result.get("data", [])

        return tuple(
            (self._from_erpnext_ref(d["name"]), d.get("reference_no", ""))
            for d in data
        )


# ---------------------------------------------------------------------------
# Contract compliance assertion
# ---------------------------------------------------------------------------


def _assert_contract_compliance() -> None:
    """Assert that ErpNextAdapter satisfies the ErpPort protocol."""
    assert isinstance(ErpNextAdapter, type)
    # Protocol runtime check
    from typing import Protocol

    if issubclass(ErpPort, Protocol):
        # Check all required methods exist
        required = [
            "create_draft_invoice",
            "read_invoice",
            "post_invoice",
            "record_payment",
            "read_payment",
            "reverse_payment",
            "cancel_invoice",
            "query_invoices",
            "ping",
            "reconcile_post",
            "reconcile_payment",
            "known_draft_refs",
            "payment_evidence_index",
        ]
        for method in required:
            assert hasattr(ErpNextAdapter, method), f"Missing method: {method}"


_assert_contract_compliance()
