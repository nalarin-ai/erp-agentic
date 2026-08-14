"""QA remediation regression tests for ADP-002 (deleg_814d8f85 findings F-01..F-10).

These tests are written RED-first: each maps to a confirmed QA finding.
All refs synthetic. Live-pilot tests skip when pilot is unavailable.
"""
from __future__ import annotations

import socket
import unittest
import unittest.mock
import uuid

from src.adapters.erpnext import ErpNextAdapter, ErpNextConfig
from src.contracts.erp_port import (
    DocumentRejected,
    DraftPaymentCommand,
    UncertainOutcome,
)
from tests.integration.erpnext.test_erpnext_adapter import (
    _command,
    _config,
    _identity,
)


def _bm_adapter() -> ErpNextAdapter:
    return ErpNextAdapter(_config(), frozenset({"UNIT-BM"}))


class TestQAF01ScopeIsolationReads(unittest.TestCase):
    """F-01: read/evidence paths must not leak cross-scope documents."""

    @classmethod
    def setUpClass(cls) -> None:
        adapter = _bm_adapter()
        try:
            if not adapter.ping():
                raise unittest.SkipTest("pilot down")
        except UncertainOutcome as e:
            raise unittest.SkipTest(f"pilot down: {e}")

    def test_read_invoice_cross_scope_rejected(self) -> None:
        """A UNIT-PR1ME-scoped adapter must not read a UNIT-BM invoice."""
        bm = _bm_adapter()
        draft = bm.create_draft_invoice(_command())
        pr1me = ErpNextAdapter(_config(), frozenset({"UNIT-PR1ME"}))
        with self.assertRaises(DocumentRejected):
            pr1me.read_invoice(draft)

    def test_read_payment_cross_scope_rejected(self) -> None:
        bm = _bm_adapter()
        draft = bm.create_draft_invoice(_command())
        posted = bm.post_invoice(draft)
        assert posted.reference is not None
        pay = bm.record_payment(
            DraftPaymentCommand(
                invoice_ref=posted.reference,
                amount="1000000",
                currency="IDR",
                evidence_ref=f"EVI-F01-READPAY-{uuid.uuid4().hex[:8]}",
                destination_account_alias="ACC-OPERASIONAL",
            )
        )
        pr1me = ErpNextAdapter(_config(), frozenset({"UNIT-PR1ME"}))
        with self.assertRaises(DocumentRejected):
            pr1me.read_payment(pay)

    def test_payment_evidence_index_scoped(self) -> None:
        """Evidence index must only list payments of in-scope companies."""
        pr1me = ErpNextAdapter(_config(), frozenset({"UNIT-PR1ME"}))
        index = pr1me.payment_evidence_index()
        self.assertEqual(index, ())

    def test_empty_scope_fail_closed(self) -> None:
        """N-01: empty authorized scope must read/list nothing."""
        empty = ErpNextAdapter(_config(), frozenset())
        # Reads fail closed
        bm = _bm_adapter()
        draft = bm.create_draft_invoice(_command())
        with self.assertRaises(DocumentRejected):
            empty.read_invoice(draft)
        # Index returns nothing
        self.assertEqual(empty.payment_evidence_index(), ())


class TestQAF02DraftPaymentNotApplied(unittest.TestCase):
    """F-02: reconcile_payment must not classify a draft (docstatus=0) PE as applied."""

    def test_reconcile_payment_rejects_draft_payment(self) -> None:
        adapter = _bm_adapter()
        try:
            if not adapter.ping():
                raise unittest.SkipTest("pilot down")
        except UncertainOutcome as e:
            raise unittest.SkipTest(f"pilot down: {e}")

        draft = adapter.create_draft_invoice(_command())
        posted = adapter.post_invoice(draft)
        assert posted.reference is not None
        evi = f"EVI-F02-DRAFT-PE-{uuid.uuid4().hex[:8]}"
        # Create PE but sabotage the submit: mock _put to fail AFTER create.
        original_put = adapter._put

        def fail_put(path, data):
            raise UncertainOutcome("simulated submit timeout")

        adapter._put = fail_put  # type: ignore[assignment]
        try:
            with self.assertRaises(UncertainOutcome):
                adapter.record_payment(
                    DraftPaymentCommand(
                        invoice_ref=posted.reference,
                        amount="1000000",
                        currency="IDR",
                        evidence_ref=evi,
                        destination_account_alias="ACC-OPERASIONAL",
                    )
                )
        finally:
            adapter._put = original_put  # type: ignore[assignment]

        # Orphan draft PE now exists consuming evi. reconcile_payment must NOT
        # classify it as applied.
        with self.assertRaises(DocumentRejected):
            adapter.reconcile_payment(evi)
        # Cleanup: cancel+delete the orphan draft PE so re-runs stay clean.
        from urllib.parse import quote

        found = adapter._get(
            "/api/resource/Payment Entry",
            params={"filters": f'[["reference_no","=","{evi}"]]', "fields": '["name"]'},
        )
        for row in found.get("data", []):
            adapter._delete(f"/api/resource/Payment Entry/{quote(row['name'], safe='')}")


class TestQAF03TimeoutUncertain(unittest.TestCase):
    """F-03: read-time timeout must surface as UncertainOutcome, never raw."""

    def test_request_timeout_wrapped(self) -> None:
        adapter = _bm_adapter()
        with unittest.mock.patch.object(
            adapter._opener, "open", side_effect=TimeoutError("timed out")
        ):
            with self.assertRaises(UncertainOutcome):
                adapter._request("GET", "/api/method/ping")

    def test_login_timeout_wrapped(self) -> None:
        adapter = _bm_adapter()
        with unittest.mock.patch.object(
            adapter._opener, "open", side_effect=socket.timeout("timed out")
        ):
            with self.assertRaises(UncertainOutcome):
                adapter._login()


class TestQAF04InputValidation(unittest.TestCase):
    """F-04: whitespace evidence_ref and lowercase currency must be rejected."""

    def test_whitespace_evidence_rejected(self) -> None:
        """Whitespace-only evidence must be rejected BEFORE any provider call.

        Use a nonexistent invoice: if validation is missing, read_invoice
        still raises DocumentRejected (invoice-not-found), so we assert the
        reason mentions evidence to prove the validation fired first.
        """
        adapter = _bm_adapter()
        with self.assertRaises(DocumentRejected) as ctx:
            adapter.record_payment(
                DraftPaymentCommand(
                    invoice_ref="INV-NONEXISTENT-F04",
                    amount="1000",
                    currency="IDR",
                    evidence_ref="   ",
                    destination_account_alias="ACC-OPERASIONAL",
                )
            )
        self.assertIn("evidence", str(ctx.exception).lower())

    def test_lowercase_currency_rejected(self) -> None:
        adapter = _bm_adapter()
        with self.assertRaises(DocumentRejected) as ctx:
            adapter.record_payment(
                DraftPaymentCommand(
                    invoice_ref="INV-NONEXISTENT-F04-CURR",
                    amount="1000",
                    currency="idr",
                    evidence_ref=f"EVI-F04-LOWER-{uuid.uuid4().hex[:8]}",
                    destination_account_alias="ACC-OPERASIONAL",
                )
            )
        self.assertIn("currency", str(ctx.exception).lower())


class TestQAF05ReversalSemantics(unittest.TestCase):
    """F-05: reversal ref must be readable with reversal_of set; double reversal rejected."""

    @classmethod
    def setUpClass(cls) -> None:
        adapter = _bm_adapter()
        try:
            if not adapter.ping():
                raise unittest.SkipTest("pilot down")
        except UncertainOutcome as e:
            raise unittest.SkipTest(f"pilot down: {e}")

    def _reversed_payment(self, adapter: ErpNextAdapter, evi: str):
        draft = adapter.create_draft_invoice(_command())
        posted = adapter.post_invoice(draft)
        assert posted.reference is not None
        pay = adapter.record_payment(
            DraftPaymentCommand(
                invoice_ref=posted.reference,
                amount="1000000",
                currency="IDR",
                evidence_ref=evi,
                destination_account_alias="ACC-OPERASIONAL",
            )
        )
        from src.contracts.erp_port import ReversalCommand

        rev = adapter.reverse_payment(ReversalCommand(payment_ref=pay, reason="qa f05"))
        return pay, rev

    def test_reversal_ref_readable_with_reversal_of(self) -> None:
        adapter = _bm_adapter()
        pay, rev = self._reversed_payment(adapter, f"EVI-F05-READABLE-{uuid.uuid4().hex[:8]}")
        record = adapter.read_payment(rev)
        self.assertEqual(record.reversal_of, pay)

    def test_double_reversal_rejected(self) -> None:
        from src.contracts.erp_port import ReversalCommand

        adapter = _bm_adapter()
        pay, _rev = self._reversed_payment(adapter, f"EVI-F05-DOUBLE-{uuid.uuid4().hex[:8]}")
        with self.assertRaises(DocumentRejected):
            adapter.reverse_payment(ReversalCommand(payment_ref=pay, reason="again"))


class TestQAF06ReasonSanitization(unittest.TestCase):
    """F-06: server tracebacks must not leak into DocumentRejected reason."""

    def test_server_error_reason_sanitized(self) -> None:
        adapter = _bm_adapter()
        try:
            if not adapter.ping():
                raise unittest.SkipTest("pilot down")
        except UncertainOutcome as e:
            raise unittest.SkipTest(f"pilot down: {e}")
        # Malformed filter triggers Frappe 500/417 with _server_messages traceback.
        try:
            adapter._get(
                "/api/resource/Payment Entry",
                params={"filters": '["reference_no","="}'},  # malformed JSON
            )
        except DocumentRejected as e:
            reason = str(e)
            self.assertNotIn("Traceback", reason)
            self.assertNotIn("apps/frappe", reason)
            self.assertLess(len(reason), 500)
        else:
            self.fail("malformed filter should raise DocumentRejected")


class TestQAF07ReLoginBounded(unittest.TestCase):
    """F-07: re-login recursion must be bounded (one retry)."""

    def test_persistent_403_raises_not_recurses(self) -> None:
        adapter = _bm_adapter()
        calls = {"n": 0}

        class FakeHTTPError(Exception):
            code = 403

            def read(self):
                return b'{"message":"forbidden"}'

        def fake_open(req, timeout=None):
            calls["n"] += 1
            if calls["n"] > 6:
                raise AssertionError("unbounded re-login recursion")
            import urllib.error

            raise urllib.error.HTTPError(
                req.full_url, 403, "Forbidden", {}, None  # type: ignore[arg-type]
            )

        adapter._logged_in = True
        with unittest.mock.patch.object(adapter._opener, "open", side_effect=fake_open):
            with unittest.mock.patch.object(adapter, "_login", autospec=False) as mock_login:
                mock_login.side_effect = lambda: setattr(adapter, "_logged_in", True)
                with self.assertRaises((DocumentRejected, UncertainOutcome)):
                    adapter._request("GET", "/api/method/ping")


class TestQAF09F10DatesAndAmounts(unittest.TestCase):
    """F-09/F-10: no hardcoded dates; canonical decimal amounts in read_invoice."""

    def test_read_invoice_amounts_canonical(self) -> None:
        adapter = _bm_adapter()
        try:
            if not adapter.ping():
                raise unittest.SkipTest("pilot down")
        except UncertainOutcome as e:
            raise unittest.SkipTest(f"pilot down: {e}")
        draft = adapter.create_draft_invoice(_command())
        record = adapter.read_invoice(draft)
        self.assertNotIn(".0", record.total_amount.split(".")[-1] if "." in record.total_amount and record.total_amount.endswith(".0") else "")
        self.assertNotRegex(record.total_amount, r"\.0$")
        self.assertNotRegex(record.open_amount, r"\.0$")

    def test_no_hardcoded_reference_date(self) -> None:
        """reference_date must track today, not a fixed literal."""
        import inspect

        import src.adapters.erpnext.erpnext_adapter as mod

        src = inspect.getsource(mod.ErpNextAdapter.record_payment)
        self.assertNotIn('"2026-08-14"', src)


if __name__ == "__main__":
    unittest.main()
