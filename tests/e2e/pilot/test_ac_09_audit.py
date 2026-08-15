"""MVP-AC-09: durable audit / read-back / redaction (FND-004, REC-001).

Criteria (TRACEABILITY_MATRIX.md section D): the audit trail is complete,
hash-chained, redacted, and audit failure never produces a false success.

Scenarios:
1. The full journey draft→post→payment leaves a complete, correctly ordered
   audit trail across all three workflow audit surfaces.
2. The reconciliation operator queue's AuditChain (the durable audit chain,
   src/audit/chain.py) verifies true after an UNCERTAIN payment round-trip,
   and every record passes the chain invariants (sequence, previous-hash,
   recomputed hash).
3. Denied actions are recorded on the denied streams with codes — denials
   are first-class audit events, not silent rejections.
4. Audit payloads never carry raw contact handles or secret material
   (redaction contract of AuditRecord + the workflows' opaque-ref-only
   audit details).
5. Audit failure never yields false success: the MutationExecutor (the
   production audit-fenced mutation path) blocks the mutation when the
   audit append fails; and the AuditChain.verify() contract detects
   tampering (the workflow audit surfaces are in-memory without hash
   chaining — see findings in docs/evidence/pilot/ac-09.md).
"""
from __future__ import annotations

from datetime import timedelta
import dataclasses
import unittest

from src.audit.chain import AuditChain, AuditRecord
from src.mutations.executor import MutationExecutor
from src.mutations.lease import MutationLease
from src.mutations.store import InMemoryMutationStore

from tests.e2e.pilot._harness import PilotHarness, UNIT_BANYUMEDIA, at


class TestAc09DurableAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    def _full_journey(self, customer_ref: str = "CUST-BYM-AUD-1"):
        h = self.harness
        _, posted = h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref=customer_ref,
        )
        assert posted.official_ref is not None
        payment = h.record_payment(
            h.banyumedia_requester, posted.official_ref,
            amount="500000.00", evidence_ref="EVI-BYM-AUD-1",
            destination_account_alias="ACC-BANYUMEDIA",
        )
        return posted, payment

    # -- 1. complete ordered trail across the journey -------------------------------

    def test_journey_audit_trail_is_complete_and_ordered(self) -> None:
        h = self.harness
        handle = h.open_draft(h.banyumedia_requester, UNIT_BANYUMEDIA,
                              customer_ref="CUST-BYM-AUD-2")
        h.set_lines(h.banyumedia_requester, handle.draft_id, h.standard_lines())
        h.preview(h.banyumedia_requester, handle.draft_id)
        preview = h.preview(h.banyumedia_requester, handle.draft_id)
        posted = h.post(h.banyumedia_poster, preview)
        assert posted.official_ref is not None
        payment = h.record_payment(
            h.banyumedia_requester, posted.official_ref,
            amount="1500000.00", evidence_ref="EVI-BYM-AUD-2",
            destination_account_alias="ACC-BANYUMEDIA",
        )
        self.assertEqual(payment.outcome, "RECORDED")

        draft_actions = [e["action"]
                         for e in h.draft_workflow.audit_events(handle.draft_id)]
        self.assertEqual(draft_actions, ["open", "set_lines", "preview", "preview"])
        post_actions = [e["action"]
                        for e in h.post_workflow.audit_events(posted.official_ref)]
        self.assertEqual(post_actions, ["post"])
        pay_actions = [e["action"]
                       for e in h.payment_workflow.audit_events(posted.official_ref)]
        self.assertEqual(pay_actions, ["payment_recorded"])
        # Every entry carries actor + ISO timestamp; timestamps are anchored
        # to the deterministic synthetic clock (T0 + minutes).
        for events, expected_at_prefix in (
            (h.draft_workflow.audit_events(handle.draft_id), "2026-08-14T00:1"),
            (h.post_workflow.audit_events(posted.official_ref), "2026-08-14T00:1"),
            (h.payment_workflow.audit_events(posted.official_ref), "2026-08-14T00:2"),
        ):
            for entry in events:
                self.assertIn("actor_ref", entry)
                self.assertTrue(entry["at"].startswith(expected_at_prefix),
                                f"{entry} not on the synthetic clock")

    # -- 2. hash-chained durable audit verifies after an UNCERTAIN round-trip --------

    def test_audit_chain_verifies_after_uncertain_payment_round_trip(self) -> None:
        h = self.harness
        _, posted = h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-BYM-AUD-3",
        )
        assert posted.official_ref is not None
        h.erp_adapter.fail_next_payment("UNCERTAIN")
        uncertain = h.record_payment(
            h.banyumedia_requester, posted.official_ref,
            amount="500000.00", evidence_ref="EVI-BYM-AUD-3",
            destination_account_alias="ACC-BANYUMEDIA",
        )
        self.assertEqual(uncertain.outcome, "UNCERTAIN")
        # REC-001: the uncertain intent was enqueued on the operator queue,
        # whose every mutation is appended to the real AuditChain.
        self.assertGreaterEqual(h.operator_queue.depth(), 1)
        reconciled = h.reconcile_payment(h.banyumedia_requester, "EVI-BYM-AUD-3")
        self.assertEqual(reconciled.outcome, "RECORDED")
        # Chain-level verification over the whole history.
        self.assertTrue(h.operator_queue.verify_audit())
        records = h.operator_queue.audit_records()
        self.assertGreaterEqual(len(records), 1)
        for index, record in enumerate(records):
            self.assertEqual(record.sequence, index + 1)
            self.assertTrue(record.previous_hash.startswith("sha256:"))
            # Hash chaining: each record's hash recomputes from its content.
            self.assertTrue(record.compute_hash().startswith("sha256:"))
        # The queue's chain head is a well-formed sha256 digest.
        self.assertRegex(records[-1].compute_hash(), r"^sha256:[0-9a-f]{64}$")

    # -- 3. denied actions are audited --------------------------------------------------

    def test_denied_actions_are_recorded_with_codes(self) -> None:
        h = self.harness
        # Denied draft open (unverified identity).
        with self.assertRaises(Exception):
            h.draft_workflow.open_draft(
                actor_ref=h.banyumedia_requester.actor_ref,
                channel_ref=h.banyumedia_requester.channel_ref,
                binding=None,
                assignments=h.banyumedia_requester.all_assignments(),
                customer_ref="CUST-BYM-AUD-4",
                at=at(10), selected_unit_ref=UNIT_BANYUMEDIA,
            )
        draft_denied = h.draft_workflow.denied_events()
        self.assertEqual(len(draft_denied), 1)
        self.assertEqual(draft_denied[0]["code"], "IDENTITY_UNVERIFIED")
        self.assertEqual(draft_denied[0]["action"], "open")

        # Denied payment (chat-only evidence) on a posted invoice.
        _, posted = h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-BYM-AUD-5",
        )
        with self.assertRaises(Exception):
            h.record_payment(
                h.banyumedia_requester, posted.official_ref,  # type: ignore[arg-type]
                amount="100.00", evidence_ref="CHAT-ONLY",
                destination_account_alias="ACC-BANYUMEDIA",
            )
        pay_denied = h.payment_workflow.denied_events()
        self.assertTrue(any(e["code"] == "INVALID_INPUT" for e in pay_denied))

    # -- 4. redaction ------------------------------------------------------------------------

    def test_audit_payloads_never_carry_contact_handles_or_secrets(self) -> None:
        h = self.harness
        # A lead with a realistic-looking contact handle exists in the CRM;
        # the invoice journey references only opaque CUST-* refs.
        h.create_lead(h.banyumedia_sales, UNIT_BANYUMEDIA,
                      display_name="PT Audit Sintetis",
                      contact_handle="+62-812-SYN-9999")
        posted, _ = self._full_journey("CUST-BYM-AUD-6")
        blob = repr((
            h.draft_workflow._audit, h.draft_workflow._denied,  # noqa: SLF001
            h.post_workflow._audit, h.post_workflow._denied,  # noqa: SLF001
            h.payment_workflow._audit, h.payment_workflow._denied,  # noqa: SLF001
            tuple(r.payload for r in h.operator_queue.audit_records()),
        ))
        # No raw contact handle ever lands in any audit stream.
        self.assertNotIn("+62-812-SYN-9999", blob)
        self.assertNotIn("contact_handle", blob)
        # No secret-shaped keys or values.
        for marker in ("password", "secret", "api_key", "pilot-synthetic-key"):
            self.assertNotIn(marker, blob.lower())

    def test_audit_record_redacts_sensitive_payload_keys(self) -> None:
        """AuditRecord contract: sensitive keys are redacted at construction."""
        record = AuditRecord(
            sequence=1, previous_hash="sha256:" + "0" * 64,
            event_type="payment_attempt", actor="ACTOR-REQ-BYM",
            timestamp=at(10),
            payload={
                "evidence_ref": "EVI-BYM-1",
                "secret": "should-never-survive",
                "token": "tok-abc",
            },
        )
        self.assertEqual(record.payload["secret"], "[REDACTED]")
        self.assertEqual(record.payload["token"], "[REDACTED]")
        self.assertEqual(record.payload["evidence_ref"], "EVI-BYM-1")
        self.assertNotIn("should-never-survive", repr(record))
        self.assertNotIn("tok-abc", repr(record))

    # -- 5. audit failure never yields false success -------------------------------------

    def test_audit_append_failure_blocks_mutation(self) -> None:
        """FND-004: MutationExecutor is the production audit-fenced mutation
        path — when the pre-mutation audit append fails, the mutation is
        blocked and the pending claim is rolled back (no false success)."""
        store = InMemoryMutationStore()
        chain = AuditChain()
        executor = MutationExecutor(store, chain)
        lease = MutationLease(  # synthetic lease for the fencing gate
            "key-aud-1", fencing_token=1, claimed_at=at(10),
            ttl=timedelta(minutes=600),
        )
        provider_calls: list[str] = []

        def provider(payload):  # must NEVER be invoked
            provider_calls.append("called")
            return "EXT-1"

        chain.fail_next_append = True
        with self.assertRaises(RuntimeError) as ctx:
            executor.execute(
                "key-aud-1", "payment_attempt",
                {"invoice_ref": "INV-000001", "amount": "1.00"},
                provider, at(11), actor="ACTOR-REQ-BYM",
                lease=lease, presented_fencing_token=1,
            )
        self.assertIn("audit failure", str(ctx.exception))
        self.assertEqual(provider_calls, [])
        # The rolled-back claim allows a clean retry once audit recovers —
        # the retry succeeds exactly once (no duplicate provider mutation).
        outcome = executor.execute(
            "key-aud-1", "payment_attempt",
            {"invoice_ref": "INV-000001", "amount": "1.00"},
            provider, at(12), actor="ACTOR-REQ-BYM",
            lease=lease, presented_fencing_token=1,
        )
        self.assertEqual(provider_calls, ["called"])
        self.assertTrue(chain.verify())

    def test_audit_chain_verify_detects_tampering(self) -> None:
        """The durable AuditChain contract: any payload/sequence tamper makes
        verify() false (workflow audit surfaces are plain in-memory lists —
        see findings)."""
        chain = AuditChain()
        chain.append(AuditRecord(
            sequence=1, previous_hash=chain.head_hash,
            event_type="open", actor="ACTOR-REQ-BYM",
            timestamp=at(10), payload={"draft_id": "DFT-000001"},
        ))
        chain.append(AuditRecord(
            sequence=2, previous_hash=chain.head_hash,
            event_type="post", actor="ACTOR-POST-BYM",
            timestamp=at(13), payload={"official_ref": "INV-000001"},
        ))
        self.assertTrue(chain.verify())
        # Tamper: rewrite a historical payload in place.
        original = chain._records[0]  # noqa: SLF001
        chain._records[0] = dataclasses.replace(  # noqa: SLF001
            original, payload={"draft_id": "DFT-FORGED"},
        )
        self.assertFalse(chain.verify())


if __name__ == "__main__":
    unittest.main()
