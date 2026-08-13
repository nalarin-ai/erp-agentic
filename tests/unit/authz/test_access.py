import unittest
from datetime import datetime, timedelta, timezone, tzinfo
import traceback
from types import SimpleNamespace

from src.authz.access import (
    AccessDecision,
    ActorUnitAssignment,
    AuthorizationRequest,
    IdentityBinding,
    PreviewBinding,
    authorize,
)


class AuthorizationBoundaryTest(unittest.TestCase):
    def test_unverified_actor_or_channel_is_denied_without_scope_disclosure(self) -> None:
        request = AuthorizationRequest(
            actor_ref="ACTOR-SYNTHETIC-01",
            channel_ref="CHANNEL-SYNTHETIC-01",
            action="LEAD-READ",
            selected_unit_ref="UNIT-BANYUMEDIA",
        )
        binding = IdentityBinding(
            actor_ref="ACTOR-SYNTHETIC-OTHER",
            channel_ref="CHANNEL-SYNTHETIC-01",
            active=True,
        )

        decision = authorize(request=request, binding=binding, assignments=())

        self.assertEqual(
            decision,
            AccessDecision.denied(code="IDENTITY_UNVERIFIED"),
        )
        self.assertNotIn("UNIT-BANYUMEDIA", decision.safe_message)

    def test_zero_one_and_multiple_assignments_resolve_context_fail_closed(self) -> None:
        binding = IdentityBinding(
            actor_ref="ACTOR-SYNTHETIC-01",
            channel_ref="CHANNEL-SYNTHETIC-01",
            active=True,
        )

        def request(selected_unit_ref: str | None = None) -> AuthorizationRequest:
            return AuthorizationRequest(
                actor_ref=binding.actor_ref,
                channel_ref=binding.channel_ref,
                action="LEAD-READ",
                selected_unit_ref=selected_unit_ref,
            )

        banyumedia = ActorUnitAssignment(
            actor_ref=binding.actor_ref,
            unit_ref="UNIT-BANYUMEDIA",
            roles=("UNIT-SALES",),
            active=True,
            assignment_ref="ASSIGNMENT-BANYUMEDIA-01",
        )
        pr1me = ActorUnitAssignment(
            actor_ref=binding.actor_ref,
            unit_ref="UNIT-PR1ME",
            roles=("UNIT-SALES",),
            active=True,
            assignment_ref="ASSIGNMENT-PR1ME-01",
        )

        no_assignment = authorize(request=request(), binding=binding, assignments=())
        one_assignment = authorize(request=request(), binding=binding, assignments=(banyumedia,))
        ambiguous = authorize(request=request(), binding=binding, assignments=(banyumedia, pr1me))
        unassigned = authorize(
            request=request("UNIT-KONTRAKTOR"),
            binding=binding,
            assignments=(banyumedia, pr1me),
        )

        self.assertEqual(no_assignment.code, "PERMISSION_DENIED")
        self.assertTrue(one_assignment.allowed)
        self.assertEqual(one_assignment.unit_ref, "UNIT-BANYUMEDIA")
        self.assertEqual(ambiguous.code, "UNIT_CONTEXT_REQUIRED")
        self.assertEqual(unassigned, AccessDecision.denied(code="PERMISSION_DENIED"))
        self.assertNotIn("UNIT-KONTRAKTOR", unassigned.safe_message)

    def test_role_permission_is_action_specific_and_never_combined_across_units(self) -> None:
        binding = IdentityBinding("ACTOR-SYNTHETIC-01", "CHANNEL-SYNTHETIC-01", True)
        sales = ActorUnitAssignment(
            actor_ref=binding.actor_ref,
            unit_ref="UNIT-BANYUMEDIA",
            roles=("UNIT-SALES",),
            active=True,
            assignment_ref="ASSIGNMENT-BANYUMEDIA-01",
        )
        reviewer_other_unit = ActorUnitAssignment(
            actor_ref=binding.actor_ref,
            unit_ref="UNIT-PR1ME",
            roles=("FINANCE-REVIEWER",),
            active=True,
            assignment_ref="ASSIGNMENT-PR1ME-01",
        )

        def decide(action: str) -> AccessDecision:
            return authorize(
                request=AuthorizationRequest(
                    actor_ref=binding.actor_ref,
                    channel_ref=binding.channel_ref,
                    action=action,
                    selected_unit_ref="UNIT-BANYUMEDIA",
                ),
                binding=binding,
                assignments=(sales, reviewer_other_unit),
            )

        self.assertTrue(decide("LEAD-READ").allowed)
        self.assertEqual(decide("INVOICE-POST").code, "PERMISSION_DENIED")
        self.assertEqual(decide("UNKNOWN-ACTION").code, "PERMISSION_DENIED")

    def test_revocation_expiry_and_stale_context_are_revalidated_per_request(self) -> None:
        now = datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)
        binding = IdentityBinding("ACTOR-SYNTHETIC-01", "CHANNEL-SYNTHETIC-01", True)

        def assignment(*, active: bool = True, revision: int = 3) -> ActorUnitAssignment:
            return ActorUnitAssignment(
                actor_ref=binding.actor_ref,
                unit_ref="UNIT-BANYUMEDIA",
                roles=("UNIT-SALES",),
                active=active,
                assignment_ref="ASSIGNMENT-SYNTHETIC-01",
                revision=revision,
                effective_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
                effective_until=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )

        def request(
            *,
            expected_revision: int = 3,
            preview: PreviewBinding | None = None,
        ) -> AuthorizationRequest:
            return AuthorizationRequest(
                actor_ref=binding.actor_ref,
                channel_ref=binding.channel_ref,
                action="LEAD-READ",
                selected_unit_ref="UNIT-BANYUMEDIA",
                requested_at=now,
                expected_assignment_revision=expected_revision,
                preview=preview,
            )

        revoked = authorize(request=request(), binding=binding, assignments=(assignment(active=False),))
        stale_context = authorize(request=request(expected_revision=2), binding=binding, assignments=(assignment(),))
        stale_preview = authorize(
            request=request(
                preview=PreviewBinding(
                    unit_ref="UNIT-PR1ME",
                    assignment_ref="ASSIGNMENT-SYNTHETIC-01",
                    assignment_revision=3,
                )
            ),
            binding=binding,
            assignments=(assignment(),),
        )

        self.assertEqual(revoked, AccessDecision.denied(code="PERMISSION_DENIED"))
        self.assertEqual(stale_context.code, "STALE_CONTEXT")
        self.assertEqual(stale_preview.code, "STALE_PREVIEW")

    def test_preview_is_bound_to_assignment_identity_not_only_unit_and_revision(self) -> None:
        now = datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)
        binding = IdentityBinding("ACTOR-X", "CHANNEL-X", True)
        replacement = ActorUnitAssignment(
            actor_ref="ACTOR-X",
            unit_ref="UNIT-X",
            roles=("UNIT-SALES",),
            active=True,
            assignment_ref="ASSIGNMENT-NEW",
            revision=1,
            effective_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
            effective_until=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        request = AuthorizationRequest(
            actor_ref="ACTOR-X",
            channel_ref="CHANNEL-X",
            action="LEAD-READ",
            selected_unit_ref="UNIT-X",
            requested_at=now,
            expected_assignment_revision=1,
            preview=PreviewBinding(
                unit_ref="UNIT-X",
                assignment_ref="ASSIGNMENT-REVOKED",
                assignment_revision=1,
            ),
        )

        self.assertEqual(
            authorize(request=request, binding=binding, assignments=(replacement,)).code,
            "STALE_PREVIEW",
        )

    def test_runtime_types_and_time_contracts_fail_at_construction(self) -> None:
        with self.assertRaises(TypeError):
            IdentityBinding("ACTOR-X", "CHANNEL-X", "yes")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ActorUnitAssignment(
                actor_ref="ACTOR-X",
                unit_ref="UNIT-X",
                roles=["UNIT-SALES"],  # type: ignore[arg-type]
                active=True,
                assignment_ref="ASSIGNMENT-X",
            )
        with self.assertRaises(ValueError):
            ActorUnitAssignment(
                actor_ref="ACTOR-X",
                unit_ref="UNIT-X",
                roles=("UNIT-SALES",),
                active=True,
                assignment_ref="ASSIGNMENT-X",
                revision=0,
            )
        with self.assertRaises(ValueError):
            AuthorizationRequest(
                actor_ref="ACTOR-X",
                channel_ref="CHANNEL-X",
                action="LEAD-READ",
                selected_unit_ref="UNIT-X",
                requested_at=datetime(2026, 8, 13, 15, 0),
            )

    def test_malformed_refs_and_duck_typed_boundary_inputs_fail_closed(self) -> None:
        for invalid_ref in ("", " ", "ＡＣＴＯＲ-X", "actor-x"):
            with self.subTest(invalid_ref=invalid_ref):
                with self.assertRaises(ValueError):
                    AuthorizationRequest(
                        actor_ref=invalid_ref,
                        channel_ref="CHANNEL-X",
                        action="LEAD-READ",
                        selected_unit_ref="UNIT-X",
                    )

        valid_request = AuthorizationRequest("ACTOR-X", "CHANNEL-X", "LEAD-READ", "UNIT-X")
        valid_binding = IdentityBinding("ACTOR-X", "CHANNEL-X", True)
        valid_assignment = ActorUnitAssignment(
            actor_ref="ACTOR-X",
            unit_ref="UNIT-X",
            roles=("UNIT-SALES",),
            active=True,
            assignment_ref="ASSIGNMENT-X",
        )
        duck = SimpleNamespace(
            actor_ref="ACTOR-X",
            channel_ref="CHANNEL-X",
            action="LEAD-READ",
            selected_unit_ref="UNIT-X",
            active=1,
            roles=("UNIT-SALES",),
            unit_ref="UNIT-X",
        )

        for request, binding, assignments in (
            (duck, valid_binding, (valid_assignment,)),
            (valid_request, duck, (valid_assignment,)),
            (valid_request, valid_binding, (duck,)),
            (valid_request, valid_binding, (object(),)),
        ):
            with self.subTest(request=type(request), binding=type(binding), assignment=type(assignments[0])):
                self.assertEqual(
                    authorize(request=request, binding=binding, assignments=assignments),  # type: ignore[arg-type]
                    AccessDecision.denied(code="INVALID_INPUT"),
                )

    def test_contract_actions_wrong_channel_foreign_actor_duplicates_and_exact_time_boundaries(self) -> None:
        start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)
        binding = IdentityBinding("ACTOR-X", "CHANNEL-X", True)
        assignment = ActorUnitAssignment(
            actor_ref="ACTOR-X",
            unit_ref="UNIT-X",
            roles=("FINANCE-REVIEWER",),
            active=True,
            assignment_ref="ASSIGNMENT-X",
            revision=4,
            effective_from=start,
            effective_until=end,
        )

        def request(at: datetime, action: str = "INVOICE_PREVIEW") -> AuthorizationRequest:
            return AuthorizationRequest(
                actor_ref="ACTOR-X",
                channel_ref="CHANNEL-X",
                action=action,
                selected_unit_ref="UNIT-X",
                requested_at=at,
            )

        self.assertTrue(authorize(request=request(start), binding=binding, assignments=(assignment,)).allowed)
        self.assertTrue(authorize(request=request(end - timedelta(microseconds=1)), binding=binding, assignments=(assignment,)).allowed)
        self.assertEqual(authorize(request=request(end), binding=binding, assignments=(assignment,)).code, "PERMISSION_DENIED")
        self.assertTrue(authorize(request=request(start, "QUERY_RECEIVABLE"), binding=binding, assignments=(assignment,)).allowed)
        self.assertEqual(authorize(request=request(start, "INVOICE_POST"), binding=binding, assignments=(assignment,)).code, "PERMISSION_DENIED")

        owner = ActorUnitAssignment(
            actor_ref="ACTOR-X",
            unit_ref="UNIT-X",
            roles=("OWNER",),
            active=True,
            assignment_ref="ASSIGNMENT-OWNER",
            effective_from=start,
            effective_until=end,
        )
        self.assertTrue(authorize(request=request(start, "QUERY_RECEIVABLE"), binding=binding, assignments=(owner,)).allowed)
        self.assertEqual(authorize(request=request(start, "INVOICE_POST"), binding=binding, assignments=(owner,)).code, "PERMISSION_DENIED")

        wrong_channel = IdentityBinding("ACTOR-X", "CHANNEL-OTHER", True)
        foreign = ActorUnitAssignment(
            actor_ref="ACTOR-OTHER",
            unit_ref="UNIT-X",
            roles=("FINANCE-REVIEWER",),
            active=True,
            assignment_ref="ASSIGNMENT-FOREIGN",
            effective_from=start,
            effective_until=end,
        )
        self.assertEqual(authorize(request=request(start), binding=wrong_channel, assignments=(assignment,)).code, "IDENTITY_UNVERIFIED")
        self.assertEqual(authorize(request=request(start), binding=binding, assignments=(foreign,)).code, "PERMISSION_DENIED")
        self.assertEqual(authorize(request=request(start), binding=binding, assignments=(assignment, assignment)).code, "PERMISSION_DENIED")

    def test_invalid_timezone_is_rejected_and_non_utc_offsets_are_comparable(self) -> None:
        class InvalidTimezone(tzinfo):
            def utcoffset(self, dt: datetime | None) -> None:
                return None

        with self.assertRaises(ValueError):
            AuthorizationRequest(
                "ACTOR-X",
                "CHANNEL-X",
                "LEAD-READ",
                "UNIT-X",
                requested_at=datetime(2026, 8, 13, 15, 0, tzinfo=InvalidTimezone()),
            )

        local = timezone(timedelta(hours=7))
        binding = IdentityBinding("ACTOR-X", "CHANNEL-X", True)
        assignment = ActorUnitAssignment(
            actor_ref="ACTOR-X",
            unit_ref="UNIT-X",
            roles=("UNIT-SALES",),
            active=True,
            assignment_ref="ASSIGNMENT-X",
            effective_from=datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc),
            effective_until=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
        )
        request = AuthorizationRequest(
            "ACTOR-X",
            "CHANNEL-X",
            "LEAD-READ",
            "UNIT-X",
            requested_at=datetime(2026, 8, 13, 15, 0, tzinfo=local),
        )
        self.assertTrue(authorize(request=request, binding=binding, assignments=(assignment,)).allowed)

    def test_hostile_iterables_and_timezones_do_not_escape_boundary(self) -> None:
        class SensitiveFailure(Exception):
            pass

        class HostileAssignments:
            def __iter__(self):
                raise KeyError("SENSITIVE-UNIT-X")

        class CustomHostileAssignments:
            def __iter__(self):
                raise SensitiveFailure("SENSITIVE-UNIT-X")

        class HostileTimezone(tzinfo):
            def utcoffset(self, dt: datetime | None):
                raise SensitiveFailure("SENSITIVE-TZ")

        request = AuthorizationRequest("ACTOR-X", "CHANNEL-X", "LEAD-READ", "UNIT-X")
        binding = IdentityBinding("ACTOR-X", "CHANNEL-X", True)
        for assignments in (HostileAssignments(), CustomHostileAssignments()):
            self.assertEqual(
                authorize(request=request, binding=binding, assignments=assignments),
                AccessDecision.denied(code="INVALID_INPUT"),
            )
        with self.assertRaisesRegex(ValueError, "timezone") as caught:
            AuthorizationRequest(
                "ACTOR-X",
                "CHANNEL-X",
                "LEAD-READ",
                "UNIT-X",
                requested_at=datetime(2026, 8, 13, 15, 0, tzinfo=HostileTimezone()),
            )
        self.assertNotIn("SENSITIVE", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        rendered = "".join(
            traceback.format_exception(
                type(caught.exception),
                caught.exception,
                caught.exception.__traceback__,
            )
        )
        self.assertNotIn("SENSITIVE", rendered)

        class ConversionHostileTimezone(tzinfo):
            calls = 0

            def utcoffset(self, dt: datetime | None):
                type(self).calls += 1
                if type(self).calls == 1:
                    return timedelta(0)
                raise SensitiveFailure("SENSITIVE-ASTIMEZONE-PAYLOAD")

        ConversionHostileTimezone.calls = 0
        with self.assertRaisesRegex(ValueError, "convertible") as conversion_caught:
            AuthorizationRequest(
                "ACTOR-X",
                "CHANNEL-X",
                "LEAD-READ",
                "UNIT-X",
                requested_at=datetime(2026, 8, 13, 15, 0, tzinfo=ConversionHostileTimezone()),
            )
        self.assertIsNone(conversion_caught.exception.__cause__)
        self.assertIsNone(conversion_caught.exception.__context__)
        conversion_rendered = "".join(
            traceback.format_exception(
                type(conversion_caught.exception),
                conversion_caught.exception,
                conversion_caught.exception.__traceback__,
            )
        )
        self.assertNotIn("SENSITIVE", conversion_rendered)

    def test_decision_invariants_reject_contradiction_and_disclosure(self) -> None:
        with self.assertRaises(ValueError):
            AccessDecision(False, "ALLOWED", "UNIT-SECRET exists", None)
        with self.assertRaises(ValueError):
            AccessDecision(True, "", "", "UNIT-X")
        with self.assertRaises(ValueError):
            AccessDecision(False, "PERMISSION_DENIED", "different message", None)

    def test_request_subclass_and_preview_revision_drift_fail_closed(self) -> None:
        class RequestSubclass(AuthorizationRequest):
            pass

        binding = IdentityBinding("ACTOR-X", "CHANNEL-X", True)
        assignment = ActorUnitAssignment(
            actor_ref="ACTOR-X",
            unit_ref="UNIT-X",
            roles=("UNIT-SALES",),
            active=True,
            assignment_ref="ASSIGNMENT-X",
            revision=7,
        )
        subclass_request = RequestSubclass("ACTOR-X", "CHANNEL-X", "LEAD-READ", "UNIT-X")
        self.assertEqual(
            authorize(request=subclass_request, binding=binding, assignments=(assignment,)),
            AccessDecision.denied(code="INVALID_INPUT"),
        )
        stale_revision = AuthorizationRequest(
            "ACTOR-X",
            "CHANNEL-X",
            "LEAD-READ",
            "UNIT-X",
            preview=PreviewBinding(
                unit_ref="UNIT-X",
                assignment_ref="ASSIGNMENT-X",
                assignment_revision=6,
            ),
        )
        self.assertEqual(
            authorize(request=stale_revision, binding=binding, assignments=(assignment,)).code,
            "STALE_PREVIEW",
        )


if __name__ == "__main__":
    unittest.main()
