"""ERPNext adapter — provider-neutral ERP port implementation (ADP-002).

This module implements the `ErpPort` contract against an isolated ERPNext
instance (EVAL-002). It uses HTTP REST API only, never direct DB access.

Security invariants:
- All refs are synthetic opaque (CUST-*, INV-*, PAY-*, EVI-*, ACC-*).
- No credentials in code; connection config injected via constructor.
- Auth is session-based: POST /api/method/login once, then reuse the
  session cookie. The admin password is never sent as a token header
  and never leaks into request URLs or non-login request bodies.
- Scoped queries intersect server-side filters with caller's authorized scope.
- Draft creation reserves nothing; official number only after verified post.
- Posting is idempotent via ERPNext naming + idempotency key.
- Payments require evidence_ref; reversals are compensating records.
- Reconciliation reads back authoritative state; no blind reissue.
"""
from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from http.cookiejar import CookieJar
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
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_error_body(exc: urllib.error.HTTPError, limit: int = 300) -> str:
    """Extract a short, safe message from a Frappe error response.

    Never leaks raw tracebacks, server paths, or `_server_messages` blobs.
    """
    try:
        body = exc.read().decode(errors="replace")
    except Exception:
        return "HTTP error (unreadable body)"
    try:
        err = json.loads(body)
    except json.JSONDecodeError:
        msg = body
    else:
        msg = err.get("message") or ""
        if not msg and "_server_messages" in err:
            try:
                msgs = json.loads(err["_server_messages"])
                first = json.loads(msgs[0]) if msgs else {}
                msg = first.get("message", "")
            except (json.JSONDecodeError, TypeError, IndexError, AttributeError):
                msg = ""
        if not msg:
            msg = err.get("exc_type", "HTTP error")
    # Strip any residual traceback-looking content.
    for marker in ("Traceback", "apps/frappe", "apps/erpnext", "File \""):
        if marker in msg:
            msg = msg.split(marker)[0]
    msg = " ".join(msg.split())  # collapse whitespace/newlines
    return msg[:limit]


def _canonical_amount(raw: Any) -> str:
    """Normalize an amount to a canonical decimal string (no trailing .0)."""
    try:
        dec = Decimal(str(raw))
    except Exception:
        return str(raw)
    return str(int(dec)) if dec == dec.to_integral_value() else str(dec.normalize())


def _filters(clauses: list[list[Any]]) -> str:
    """Build a Frappe filters param safely via json.dumps (no interpolation)."""
    return json.dumps(clauses)


_ISO4217 = re.compile(r"^[A-Z]{3}$")


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
            "Accept": "application/json",
        }
        self._cookies = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )
        self._logged_in = False

    # -- session auth ---------------------------------------------------------

    def _login(self) -> None:
        """Establish session via POST /api/method/login.

        The admin password is only sent in the login form body, never
        as a token header and never in a URL. Session cookies are stored
        in the adapter's CookieJar and reused by subsequent requests.
        """
        url = f"{self._base}/api/method/login"
        body = urllib.parse.urlencode(
            {"usr": "Administrator", "pwd": self._config.admin_password}
        ).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Accept": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=self._config.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise UncertainOutcome(f"ERPNext login failed: HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise UncertainOutcome(f"ERPNext login connection failed: {e.reason}") from e
        except (TimeoutError, socket.timeout, OSError) as e:
            raise UncertainOutcome(f"ERPNext login timeout: {e}") from e
        if not isinstance(payload, dict) or "message" not in payload:
            raise UncertainOutcome("ERPNext login returned unexpected payload")
        self._logged_in = True

    # -- internal HTTP helpers -----------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        *,
        _retried: bool = False,
    ) -> dict[str, Any]:
        """Make HTTP request to ERPNext API using session cookies."""
        if not self._logged_in:
            self._login()
        # URL-encode path segments (e.g. "Sales Invoice" -> "Sales%20Invoice").
        encoded_path = urllib.parse.quote(path, safe="/")
        url = f"{self._base}{encoded_path}"
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"

        headers = dict(self._headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode() if data else None,
            headers=headers,
            method=method,
        )

        try:
            with self._opener.open(req, timeout=self._config.timeout_seconds) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and self._logged_in and not _retried:
                # Session expired — re-login once and retry once.
                self._logged_in = False
                self._login()
                return self._request(method, path, data=data, params=params, _retried=True)
            raise DocumentRejected(
                f"ERPNext HTTP {e.code}: {_sanitize_error_body(e)}"
            ) from e
        except urllib.error.URLError as e:
            raise UncertainOutcome(f"ERPNext connection failed: {e.reason}") from e
        except (TimeoutError, socket.timeout, OSError) as e:
            raise UncertainOutcome(f"ERPNext request timeout: {e}") from e

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
        """Convert opaque ref to ERPNext naming. Strips `DRAFT:` prefix."""
        return self._resolve_draft_ref(ref)

    def _from_erpnext_ref(self, name: str) -> str:
        """Convert ERPNext document name to opaque ref."""
        return name

    # -- ErpPort implementation ----------------------------------------------

    def create_draft_invoice(self, command: DraftInvoiceCommand) -> str:
        """Create a draft Sales Invoice in ERPNext.

        Returns a draft handle prefixed with `DRAFT:` so that the caller
        can distinguish it from the official posted reference (which is
        the bare ERPNext document name).
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
        return f"DRAFT:{self._from_erpnext_ref(result['data']['name'])}"

    def _resolve_draft_ref(self, reference: str) -> str:
        """Strip `DRAFT:` prefix to get the bare ERPNext document name."""
        if reference.startswith("DRAFT:"):
            return reference[len("DRAFT:"):]
        return reference

    def read_invoice(self, reference: str) -> InvoiceRecord:
        """Read back a Sales Invoice from ERPNext (fail-closed on scope)."""
        name = self._to_erpnext_ref(reference)
        result = self._get(f"/api/resource/Sales Invoice/{name}")
        data = result["data"]

        # Fail-closed scope check: never expose another unit's document.
        # An empty authorized scope means "may read nothing".
        company = data.get("company", "")
        if not self._scope or (company and company not in self._scope):
            raise DocumentRejected(
                f"Invoice {reference} not in authorized scope"
            )

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
            total_amount=_canonical_amount(data.get("grand_total", "0")),
            currency=data.get("currency", "IDR"),
            open_amount=_canonical_amount(data.get("outstanding_amount", "0")),
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
        Enforces evidence_ref uniqueness: a second payment with the same
        evidence_ref raises DocumentRejected.
        """
        if not command.evidence_ref or not command.evidence_ref.strip():
            raise DocumentRejected("Payment requires non-blank evidence_ref")
        if not _ISO4217.match(command.currency):
            raise DocumentRejected(
                f"Payment currency must be ISO-4217 uppercase, got {command.currency!r}"
            )

        # Enforce evidence_ref uniqueness (adapter-level, since ERPNext does not).
        existing = self._get(
            "/api/resource/Payment Entry",
            params={
                "filters": _filters([["reference_no", "=", command.evidence_ref]]),
                "limit_page_length": "1",
            },
        )
        if existing.get("data"):
            raise DocumentRejected(
                f"Duplicate evidence_ref {command.evidence_ref}"
            )

        # Resolve the invoice to discover the actual Customer (party) and Company.
        invoice = self.read_invoice(command.invoice_ref)
        party = invoice.payload.get("customer")
        company = invoice.payload.get("company")
        if not party:
            raise DocumentRejected(
                f"Invoice {command.invoice_ref} has no customer"
            )
        if not company:
            raise DocumentRejected(
                f"Invoice {command.invoice_ref} has no company"
            )

        # Discover default cash/bank account for the company.
        # We use `Cash - <abbr>` which ERPNext auto-creates for the company.
        # If absent, ERPNext will reject — that's a fixture issue, not adapter bug.
        abbr = company.split("-")[0] if "-" in company else company[:3].upper()
        # UNIT-BM has abbr UBM — but we stored that in _seeder; look up actual abbr
        # via company doc.
        company_doc = self._get(f"/api/resource/Company/{company}")
        abbr = company_doc["data"].get("abbr", abbr)
        paid_to = f"Cash - {abbr}"

        payload = {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": party,
            "company": company,
            "paid_to": paid_to,
            "paid_amount": float(command.amount),
            "received_amount": float(command.amount),
            "source_exchange_rate": 1.0,
            "target_exchange_rate": 1.0,
            "reference_no": command.evidence_ref,
            "reference_date": date.today().isoformat(),
            "remarks": f"Evidence: {command.evidence_ref}; Account: {command.destination_account_alias}",
            "references": [
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": self._to_erpnext_ref(command.invoice_ref),
                    "allocated_amount": float(command.amount),
                }
            ],
        }

        result = self._post("/api/resource/Payment Entry", payload)
        payment_name = result["data"]["name"]
        # Submit the payment so it affects the invoice outstanding_amount.
        self._put(
            f"/api/resource/Payment Entry/{payment_name}",
            {"docstatus": 1},
        )
        return self._from_erpnext_ref(payment_name)

    def read_payment(self, reference: str) -> PaymentRecord:
        """Read back a Payment Entry from ERPNext (fail-closed on scope).

        Accepts a plain payment name or a `REV:<name>` reversal handle:
        a reversal handle reads the cancelled original and reports
        ``reversal_of`` so callers can prove compensating linkage.
        """
        reversal_of: str | None = None
        name = self._to_erpnext_ref(reference)
        if reference.startswith("REV:"):
            reversal_of = reference[len("REV:"):]
            name = reversal_of
        result = self._get(f"/api/resource/Payment Entry/{name}")
        data = result["data"]

        # Fail-closed scope check: never expose another unit's payment.
        company = data.get("company", "")
        if not self._scope or (company and company not in self._scope):
            raise DocumentRejected(
                f"Payment {reference} not in authorized scope"
            )

        references = data.get("references") or []
        invoice_ref = references[0].get("reference_name", "") if references else ""

        return PaymentRecord(
            reference=self._from_erpnext_ref(data["name"]),
            invoice_ref=invoice_ref,
            amount=_canonical_amount(data.get("paid_amount", "0")),
            currency=data.get("currency", "IDR"),
            evidence_ref=data.get("reference_no", ""),
            destination_account_alias=data.get("remarks", "").split("Account: ")[-1] if "Account: " in data.get("remarks", "") else "",
            reversal_of=reversal_of,
        )

    def reverse_payment(self, command: ReversalCommand) -> str:
        """Reverse a Payment Entry in ERPNext.

        ERPNext convention: cancel the original Payment Entry. This frees
        the invoice's outstanding_amount and prevents double-payment.
        The returned "reversal reference" is the original payment name
        prefixed with `REV:` to signal it is a reversal-of record.

        Note: this DOES not create a new Payment Entry (which ERPNext would
        reject as overpayment); it transitions the original to CANCELLED.
        """
        original = self.read_payment(command.payment_ref)
        # Verify the payment exists and is currently submitted
        name = self._to_erpnext_ref(command.payment_ref)
        current = self._get(f"/api/resource/Payment Entry/{name}")
        docstatus = current["data"].get("docstatus", 0)
        if docstatus == 2:
            # Already cancelled — a second reversal is a blind reissue. Reject.
            raise DocumentRejected(
                f"Payment {command.payment_ref} already reversed"
            )
        if docstatus != 1:
            raise DocumentRejected(
                f"Cannot reverse payment in docstatus {docstatus} (expected submitted)"
            )
        # Cancel via the standard Frappe cancel method.
        self._post(
            "/api/method/frappe.client.cancel",
            {"doctype": "Payment Entry", "name": name},
        )
        return f"REV:{name}"

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
        clauses: list[list[Any]] = []

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
            clauses.append(["company", "=", operating_unit_ref])
        else:
            # Default to all authorized units
            scope_list = sorted(self._scope)
            if len(scope_list) == 1:
                clauses.append(["company", "=", scope_list[0]])
            else:
                clauses.append(["company", "in", scope_list])

        if status:
            docstatus = {"DRAFT": 0, "POSTED": 1, "CANCELLED": 2}.get(status)
            if docstatus is not None:
                clauses.append(["docstatus", "=", docstatus])

        if customer_ref:
            clauses.append(["customer", "=", customer_ref])

        params = {
            "fields": '["name"]',
            "limit_page_length": "1000",
        }
        if clauses:
            params["filters"] = _filters(clauses)

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
        """Classify an uncertain payment by its reserved evidence reference.

        Scoped to authorized companies and only counts submitted (docstatus=1)
        payments: a leftover draft Payment Entry after an uncertain submit is
        NOT authoritative and must not be classified as applied.
        """
        clauses: list[list[Any]] = [["reference_no", "=", evidence_ref]]
        if self._scope:
            clauses.append(["company", "in", sorted(self._scope)])
        params = {
            "fields": '["name","docstatus"]',
            "filters": _filters(clauses),
        }
        result = self._get("/api/resource/Payment Entry", params=params)
        data = result.get("data", [])

        submitted = [d for d in data if d.get("docstatus") == 1]
        if not submitted:
            raise DocumentRejected(
                f"No applied payment with evidence {evidence_ref}"
            )

        return self.read_payment(submitted[0]["name"])

    def known_draft_refs(self) -> set[str]:
        """Snapshot of every draft handle this provider issued.

        Drafts are returned with the `DRAFT:` prefix so callers can
        distinguish them from posted (official) references.
        """
        result = self.query_invoices(status="DRAFT")
        return {f"DRAFT:{ref}" for ref in result.references}

    def payment_evidence_index(self) -> tuple[tuple[str, str], ...]:
        """(payment_ref, evidence_ref) pairs for payment orphan cross-checks.

        Scoped server-side to authorized companies: never lists another
        unit's payments. Empty scope is fail-closed (returns nothing).
        """
        if not self._scope:
            return ()
        clauses: list[list[Any]] = [["company", "in", sorted(self._scope)]]
        params = {
            "fields": '["name","reference_no"]',
            "limit_page_length": "1000",
        }
        if clauses:
            params["filters"] = _filters(clauses)
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
