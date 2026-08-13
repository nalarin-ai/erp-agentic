from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Iterable


_REGISTERED_ACTIONS = frozenset(
    {
        "LEAD-READ",
        "LEAD-WRITE",
        "QUOTATION-DRAFT",
        "INVOICE_PREVIEW",
        "INVOICE_POST",
        "PAYMENT_RECORD",
        "QUERY_RECEIVABLE",
    }
)
_ROLE_ACTIONS = {
    "UNIT-SALES": frozenset({"LEAD-READ", "LEAD-WRITE", "QUOTATION-DRAFT"}),
    "FINANCE-REQUESTER": frozenset({"QUOTATION-DRAFT", "INVOICE_PREVIEW", "PAYMENT_RECORD"}),
    "FINANCE-REVIEWER": frozenset(
        {"LEAD-READ", "QUOTATION-DRAFT", "INVOICE_PREVIEW", "PAYMENT_RECORD", "QUERY_RECEIVABLE"}
    ),
    "OWNER": frozenset(
        {
            "LEAD-READ",
            "LEAD-WRITE",
            "QUOTATION-DRAFT",
            "INVOICE_PREVIEW",
            "PAYMENT_RECORD",
            "QUERY_RECEIVABLE",
        }
    ),
}
_REF = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
_ROLE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_ACTION = re.compile(r"^[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+$")
_DENIAL_CODES = frozenset(
    {
        "IDENTITY_UNVERIFIED",
        "INVALID_INPUT",
        "PERMISSION_DENIED",
        "STALE_CONTEXT",
        "STALE_PREVIEW",
        "UNIT_CONTEXT_REQUIRED",
    }
)
_DENIAL_MESSAGE = "Request cannot be authorized."


def _require_ref(value: object, prefix: str, name: str) -> None:
    if type(value) is not str or _REF.fullmatch(value) is None or not value.startswith(prefix):
        raise ValueError(f"{name} must be a canonical {prefix.removesuffix('-')} reference")


def _as_utc(value: datetime, name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{name} must be datetime")
    offset_failed = False
    try:
        offset = value.utcoffset()
    except Exception:
        offset = None
        offset_failed = True
    if offset_failed:
        raise ValueError(f"{name} must have a valid timezone offset")
    if offset is None:
        raise ValueError(f"{name} must be timezone-aware")
    conversion_failed = False
    try:
        converted = value.astimezone(timezone.utc)
    except Exception:
        converted = None
        conversion_failed = True
    if conversion_failed:
        raise ValueError(f"{name} must be convertible to UTC")
    if converted is None:
        raise ValueError(f"{name} must be convertible to UTC")
    return converted


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    actor_ref: str
    channel_ref: str
    action: str
    selected_unit_ref: str | None
    requested_at: datetime | None = None
    expected_assignment_revision: int | None = None
    preview: PreviewBinding | None = None

    def __post_init__(self) -> None:
        _require_ref(self.actor_ref, "ACTOR-", "actor_ref")
        _require_ref(self.channel_ref, "CHANNEL-", "channel_ref")
        if self.selected_unit_ref is not None:
            _require_ref(self.selected_unit_ref, "UNIT-", "selected_unit_ref")
        if type(self.action) is not str or _ACTION.fullmatch(self.action) is None:
            raise ValueError("action must be canonical")
        if self.requested_at is not None:
            _as_utc(self.requested_at, "requested_at")
        if self.expected_assignment_revision is not None and (
            type(self.expected_assignment_revision) is not int
            or self.expected_assignment_revision < 1
        ):
            raise ValueError("expected_assignment_revision must be a positive integer")
        if self.preview is not None and type(self.preview) is not PreviewBinding:
            raise TypeError("preview must be PreviewBinding")


@dataclass(frozen=True, slots=True)
class IdentityBinding:
    actor_ref: str
    channel_ref: str
    active: bool

    def __post_init__(self) -> None:
        _require_ref(self.actor_ref, "ACTOR-", "actor_ref")
        _require_ref(self.channel_ref, "CHANNEL-", "channel_ref")
        if type(self.active) is not bool:
            raise TypeError("active must be bool")


@dataclass(frozen=True, slots=True)
class ActorUnitAssignment:
    actor_ref: str
    unit_ref: str
    roles: tuple[str, ...]
    active: bool
    assignment_ref: str
    revision: int = 1
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    def __post_init__(self) -> None:
        _require_ref(self.actor_ref, "ACTOR-", "actor_ref")
        _require_ref(self.unit_ref, "UNIT-", "unit_ref")
        _require_ref(self.assignment_ref, "ASSIGNMENT-", "assignment_ref")
        if type(self.active) is not bool:
            raise TypeError("active must be bool")
        if type(self.roles) is not tuple or not all(type(role) is str for role in self.roles):
            raise TypeError("roles must be a tuple of strings")
        if not self.roles or any(_ROLE.fullmatch(role) is None for role in self.roles):
            raise ValueError("roles must be non-empty canonical role names")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        effective_from = _as_utc(self.effective_from, "effective_from") if self.effective_from is not None else None
        effective_until = _as_utc(self.effective_until, "effective_until") if self.effective_until is not None else None
        if effective_from is not None and effective_until is not None and effective_from >= effective_until:
            raise ValueError("effective interval must be non-empty")


@dataclass(frozen=True, slots=True)
class PreviewBinding:
    unit_ref: str
    assignment_ref: str
    assignment_revision: int

    def __post_init__(self) -> None:
        _require_ref(self.unit_ref, "UNIT-", "unit_ref")
        _require_ref(self.assignment_ref, "ASSIGNMENT-", "assignment_ref")
        if type(self.assignment_revision) is not int or self.assignment_revision < 1:
            raise ValueError("assignment_revision must be a positive integer")


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    code: str
    safe_message: str
    unit_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool or type(self.code) is not str or type(self.safe_message) is not str:
            raise TypeError("decision fields have invalid types")
        if self.allowed:
            if self.code != "ALLOWED" or self.safe_message != "Allowed.":
                raise ValueError("allowed decision has invalid code or message")
            if self.unit_ref is None:
                raise ValueError("allowed decision requires unit_ref")
            _require_ref(self.unit_ref, "UNIT-", "unit_ref")
        else:
            if self.code not in _DENIAL_CODES or self.safe_message != _DENIAL_MESSAGE:
                raise ValueError("denied decision has invalid code or message")
            if self.unit_ref is not None:
                raise ValueError("denied decision cannot disclose unit_ref")

    @classmethod
    def denied(cls, code: str) -> AccessDecision:
        return cls(allowed=False, code=code, safe_message=_DENIAL_MESSAGE)


def authorize(
    *,
    request: AuthorizationRequest,
    binding: IdentityBinding | None,
    assignments: Iterable[ActorUnitAssignment],
) -> AccessDecision:
    if type(request) is not AuthorizationRequest or (
        binding is not None and type(binding) is not IdentityBinding
    ):
        return AccessDecision.denied(code="INVALID_INPUT")
    try:
        materialized_assignments = tuple(assignments)
    except Exception:
        return AccessDecision.denied(code="INVALID_INPUT")
    if any(type(assignment) is not ActorUnitAssignment for assignment in materialized_assignments):
        return AccessDecision.denied(code="INVALID_INPUT")
    if (
        binding is None
        or not binding.active
        or binding.actor_ref != request.actor_ref
        or binding.channel_ref != request.channel_ref
    ):
        return AccessDecision.denied(code="IDENTITY_UNVERIFIED")

    active_assignments = tuple(
        assignment
        for assignment in materialized_assignments
        if _assignment_is_effective(assignment, request)
    )
    if request.selected_unit_ref is not None:
        matching = tuple(
            assignment
            for assignment in active_assignments
            if assignment.unit_ref == request.selected_unit_ref
        )
        if len(matching) != 1:
            return AccessDecision.denied(code="PERMISSION_DENIED")
        selected = matching[0]
    elif len(active_assignments) == 1:
        selected = active_assignments[0]
    elif len(active_assignments) > 1:
        return AccessDecision.denied(code="UNIT_CONTEXT_REQUIRED")
    else:
        return AccessDecision.denied(code="PERMISSION_DENIED")

    if (
        request.expected_assignment_revision is not None
        and selected.revision != request.expected_assignment_revision
    ):
        return AccessDecision.denied(code="STALE_CONTEXT")
    if request.preview is not None and (
        request.preview.unit_ref != selected.unit_ref
        or request.preview.assignment_ref != selected.assignment_ref
        or request.preview.assignment_revision != selected.revision
    ):
        return AccessDecision.denied(code="STALE_PREVIEW")

    allowed_actions = frozenset().union(
        *(_ROLE_ACTIONS.get(role, frozenset()) for role in selected.roles)
    )
    if request.action not in _REGISTERED_ACTIONS or request.action not in allowed_actions:
        return AccessDecision.denied(code="PERMISSION_DENIED")

    return AccessDecision(
        allowed=True,
        code="ALLOWED",
        safe_message="Allowed.",
        unit_ref=selected.unit_ref,
    )


def _assignment_is_effective(
    assignment: ActorUnitAssignment,
    request: AuthorizationRequest,
) -> bool:
    if not assignment.active or assignment.actor_ref != request.actor_ref:
        return False
    if request.requested_at is None:
        return assignment.effective_from is None and assignment.effective_until is None
    requested_at = _as_utc(request.requested_at, "requested_at")
    if assignment.effective_from is not None:
        if requested_at < _as_utc(assignment.effective_from, "effective_from"):
            return False
    if assignment.effective_until is not None:
        if requested_at >= _as_utc(assignment.effective_until, "effective_until"):
            return False
    return True
