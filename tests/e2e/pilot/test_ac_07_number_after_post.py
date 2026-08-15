"""MVP-AC-07: official number / PDF exist ONLY after a verified post (FLOW-002).

Criteria (TRACEABILITY_MATRIX.md section D): a draft can never claim an
official number:

1. Draft snapshots and previews expose NO official_ref and no PDF document
   reference; the preview's account alias stays redacted (ACC-[REDACTED]).
2. render_for_review produces a review payload, not an official document —
   no official number, no pdf reference field.
3. The official number (and pdf_reference) appear ONLY after post() succeeds.
4. get_posted_invoice before any post is a fail-closed error (unknown ref).
5. A tampered caller-supplied preview can never be forged into a post —
   _verify_preview_authentic denies it (PREVIEW_HASH_MISMATCH) and the
   provider sees zero writes from the attempt.
"""
from __future__ import annotations

import dataclasses
import unittest

from src.workflows.invoice_post.workflow import (
    WorkflowBlocked as PostBlocked,
    WorkflowDenied as PostDenied,
)

from tests.e2e.pilot._harness import PilotHarness, UNIT_BANYUMEDIA


def _provider_write_count(h: PilotHarness) -> int:
    return len(h.erp_adapter._invoices)  # noqa: SLF001 - test inspection


class TestAc07NumberOnlyAfterPost(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    def _open_preview(self, customer_ref: str = "CUST-BYM-NUM-1"):
        h = self.harness
        handle = h.open_draft(h.banyumedia_requester, UNIT_BANYUMEDIA,
                              customer_ref=customer_ref)
        h.set_lines(h.banyumedia_requester, handle.draft_id,
                    h.standard_lines())
        preview = h.preview(h.banyumedia_requester, handle.draft_id)
        return handle, preview

    # -- 1. draft/preview carry no official identity ----------------------------

    def test_draft_snapshot_exposes_no_official_ref_or_pdf(self) -> None:
        h = self.harness
        handle, _ = self._open_preview()
        snapshot = h.draft_workflow.get_draft(handle.draft_id)
        # DraftSnapshot is the read model served to chat callers: it has no
        # official_ref / pdf_reference surface at all.
        self.assertFalse(hasattr(snapshot, "official_ref"))
        self.assertFalse(hasattr(snapshot, "pdf_reference"))
        self.assertEqual(snapshot.status, "OPEN")

    def test_preview_exposes_no_official_number_and_redacts_account(self) -> None:
        _, preview = self._open_preview()
        self.assertFalse(hasattr(preview, "official_ref"))
        self.assertFalse(hasattr(preview, "pdf_reference"))
        # The preview never reveals the real destination account alias.
        self.assertEqual(preview.destination_account_alias, "ACC-[REDACTED]")
        # The preview hash binds the content but is NOT an official number.
        self.assertNotRegex(preview.preview_hash, r"^INV-\d{6}$")

    # -- 2. render_for_review is not an official document -------------------------

    def test_render_for_review_payload_is_not_official_document(self) -> None:
        h = self.harness
        _, preview = self._open_preview()
        payload = h.draft_workflow.render_for_review(
            preview,
            at=__import__("tests.e2e.pilot._harness", fromlist=["at"]).at(13),
            actor_ref=h.banyumedia_requester.actor_ref,
            binding=h.banyumedia_requester.binding,
            assignments=h.banyumedia_requester.all_assignments(),
        )
        self.assertNotIn("official_ref", payload)
        self.assertNotIn("pdf_reference", payload)
        self.assertIn("preview_hash", payload)

    # -- 3. official number + pdf only after post ---------------------------------

    def test_official_number_and_pdf_reference_appear_only_after_post(self) -> None:
        h = self.harness
        before = _provider_write_count(h)
        _, preview = self._open_preview()
        # Pre-post: nothing addressable as a posted invoice, no provider write.
        self.assertEqual(_provider_write_count(h), before)
        self.assertNotIn(preview.draft_id, h.post_workflow._by_draft_id)  # noqa: SLF001
        result = h.post(h.banyumedia_poster, preview)
        self.assertEqual(result.outcome, "POSTED")
        self.assertIsNotNone(result.official_ref)
        record = h.get_posted_invoice(result.official_ref)  # type: ignore[arg-type]
        self.assertEqual(record.official_ref, result.official_ref)
        self.assertTrue(record.pdf_reference)
        self.assertIn(result.official_ref, record.pdf_reference)  # type: ignore[operator]

    # -- 4. read-back before post fails closed --------------------------------------

    def test_get_posted_invoice_before_post_is_denied(self) -> None:
        h = self.harness
        _, preview = self._open_preview()
        with self.assertRaises(PostBlocked) as ctx:
            h.get_posted_invoice(preview.draft_id)
        self.assertIn("unknown posted invoice", str(ctx.exception))
        with self.assertRaises(PostBlocked):
            h.get_posted_invoice("INV-999999")  # never issued

    # -- 5. tampered preview can never be forged into a post ------------------------

    def test_tampered_preview_post_denied_zero_provider_write(self) -> None:
        h = self.harness
        _, preview = self._open_preview()
        before = _provider_write_count(h)
        forged = dataclasses.replace(preview, total_amount="1.00")
        with self.assertRaises(PostDenied) as ctx:
            h.post(h.banyumedia_poster, forged)
        self.assertEqual(ctx.exception.code, "PREVIEW_HASH_MISMATCH")
        self.assertEqual(_provider_write_count(h), before)
        # The forgery attempt is audited on the denied stream.
        codes = [e["code"] for e in h.post_workflow.denied_events()
                 if e["action"] == "post"]
        self.assertIn("PREVIEW_HASH_MISMATCH", codes)

    def test_tampered_preview_hash_post_denied(self) -> None:
        h = self.harness
        _, preview = self._open_preview()
        before = _provider_write_count(h)
        forged = dataclasses.replace(preview, preview_hash="0" * 64)
        with self.assertRaises(PostDenied) as ctx:
            h.post(h.banyumedia_poster, forged)
        self.assertEqual(ctx.exception.code, "PREVIEW_HASH_MISMATCH")
        self.assertEqual(_provider_write_count(h), before)


if __name__ == "__main__":
    unittest.main()
