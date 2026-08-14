"""Crash-safe mutation executor.

Implements R-007/R-008: one mutation under retry, crash boundaries, terminal
audit failure, fencing/lease enforcement, and recovery. Never executes blind
retries.

Remediation round 1 (independent QA FAIL -> revision):
- QA-01: a retry observing a non-terminal claim (PENDING/UNCERTAIN) raises
  RecoveryRequired instead of re-invoking the provider.
- QA-03: local terminal write and terminal success audit are separated; if
  the success audit fails, the outcome is transitioned to UNCERTAIN so the
  store never contradicts the audit trail.
- QA-05: execute() binds the presented key to the derived idempotency key
  (namespace, action=event_type, payload, canonicalization_version) and
  fails closed on mismatch.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, Callable

from src.audit.chain import AuditChain, AuditRecord
from src.mutations.idempotency import IdempotencyKey
from src.mutations.lease import MutationLease, StaleFencingTokenError
from src.mutations.store import InMemoryMutationStore, MutationOutcome, MutationStatus


class RecoveryRequired(RuntimeError):
    """The key is already claimed and non-terminal; a fenced recovery pass
    must classify it before any provider reissue (never blind replay)."""


class MutationExecutor:
    """Executes mutations with idempotency, fencing, and audit."""

    def __init__(self, store: InMemoryMutationStore, audit: AuditChain) -> None:
        self._store = store
        self._audit = audit

    def _payload_hash(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _audit_event(self, event_type: str, actor: str, at: datetime, payload: dict[str, Any]) -> None:
        self._audit.append(AuditRecord(
            sequence=len(self._audit) + 1,
            previous_hash=self._audit.head_hash,
            event_type=event_type,
            actor=actor,
            timestamp=at,
            payload=payload,
        ))

    def execute(
        self,
        key: str,
        event_type: str,
        payload: dict[str, Any],
        provider: Callable[[dict[str, Any]], str],
        at: datetime,
        *,
        actor: str,
        lease: MutationLease,
        presented_fencing_token: int,
        namespace: str | None = None,
        canonicalization_version: int = 1,
    ) -> MutationOutcome:
        """Execute a mutation with idempotency, fencing, and crash safety."""
        # Enforce fencing/lease before any work: the presented token must match
        # the lease's current token and the lease must not be expired.
        lease.assert_fresh(presented_fencing_token, at)

        # QA-05: when a namespace is supplied, the presented key must equal the
        # derived idempotency key for this payload+version. Fail closed before
        # any store write or provider call.
        if namespace is not None:
            derived = IdempotencyKey.derive(
                namespace, event_type, payload,
                canonicalization_version=canonicalization_version,
            )
            if derived.value != key:
                raise ValueError(
                    "presented key does not match derived idempotency key"
                )

        # The claim binds the fencing token into the store so a later stale
        # writer can be rejected even if it constructs a fresh lease object.
        register = getattr(self._store, "register_fencing", None)
        if callable(register):
            register(key, lease.fencing_token)

        payload_hash = self._payload_hash(payload)

        # CAS claim: returns existing or raises on conflict
        outcome = self._store.claim(key, payload_hash)
        if outcome.status in (
            MutationStatus.RESOLVED_PRESENT,
            MutationStatus.RESOLVED_ABSENT,
            MutationStatus.FAILED_NO_MUTATION,
        ):
            return outcome
        # QA-01: an existing non-terminal claim (PENDING/UNCERTAIN) belongs to
        # an in-flight or crashed worker. Never re-invoke the provider; force
        # a fenced recovery/classification pass instead. A claim freshly
        # created by *this* call carries created=True and proceeds.
        if not outcome.created:
            raise RecoveryRequired(f"key {key[:16]}… is claimed and non-terminal")

        # Audit before mutation (fail-closed)
        try:
            self._audit_event(event_type, actor, at, {
                "key": key, "action": "pre_mutation", "fencing_token": lease.fencing_token,
            })
        except RuntimeError:
            # Rollback the pending claim created above
            self._store.rollback_claim(key)
            raise RuntimeError("terminal audit failure; mutation blocked")

        # Execute provider
        try:
            external_ref = provider(payload)
        except RuntimeError:
            self._store.write_failure(key, MutationStatus.FAILED_NO_MUTATION)
            self._audit_event(event_type, actor, at, {
                "key": key, "action": "provider_failed", "error": "provider_error",
            })
            raise

        # QA-03: local terminal write first, terminal success audit second.
        # A failure of the success audit transitions the outcome to UNCERTAIN
        # so store and audit never disagree about terminality.
        try:
            result = self._store.write_success(key, external_ref, external_ref)
        except RuntimeError:
            # Local write failed after provider success; store already recorded
            # UNCERTAIN with external_reference preserved for recovery.
            self._audit_event(event_type, actor, at, {
                "key": key, "action": "local_write_failed",
                "external_reference": external_ref, "status": "uncertain",
            })
            raise

        try:
            self._audit_event(event_type, actor, at, {
                "key": key, "action": "post_mutation",
                "external_reference": external_ref, "status": "success",
            })
        except RuntimeError:
            # Terminal audit failed after the store recorded success: downgrade
            # to UNCERTAIN so a fenced recovery pass reconciles reality, and
            # record the uncertainty if the chain still accepts appends.
            self._store.resolve(key, MutationStatus.UNCERTAIN, external_ref)
            try:
                self._audit_event(event_type, actor, at, {
                    "key": key, "action": "terminal_audit_failed",
                    "external_reference": external_ref, "status": "uncertain",
                })
            except RuntimeError:
                pass
            raise RuntimeError("terminal audit failure after local success; outcome uncertain")
        return result

    def recover(
        self,
        key: str,
        at: datetime,
        *,
        actor: str,
        lease: MutationLease,
        presented_fencing_token: int,
    ) -> MutationOutcome:
        """Recover an uncertain outcome via read-back.

        Recovery is a mutation-path action: the caller must present the
        current fencing token for this key and a non-expired lease. A stale
        worker is rejected before any state change (contract: lease expiry
        permits reconciliation takeover, never blind replay).
        """
        lease.assert_fresh(presented_fencing_token, at)
        if lease.key != key:
            raise ValueError("lease key does not match recovery key")
        # Reject recovery from a fencing token that is not the recorded owner
        # of this key. A token different from the registered owner token means
        # a stale or foreign worker; recovery must not finalize state.
        owner_token_of = getattr(self._store, "current_fencing_token", None)
        if callable(owner_token_of):
            recorded = owner_token_of(key)
            if recorded and lease.fencing_token != recorded:
                raise StaleFencingTokenError(
                    f"stale fencing token on recovery: {lease.fencing_token} != {recorded}"
                )
        outcome = self._store.get(key)
        if outcome is None:
            raise ValueError("unknown key")
        if outcome.status != MutationStatus.UNCERTAIN:
            return outcome
        # Simulate read-back: if external ref exists, resolve present
        if outcome.external_reference:
            resolved = self._store.resolve(key, MutationStatus.RESOLVED_PRESENT, outcome.external_reference)
            self._audit_event("RECOVERY", actor, at, {
                "key": key, "action": "recovered", "status": "resolved_present",
                "external_reference": outcome.external_reference,
            })
            return resolved
        resolved = self._store.resolve(key, MutationStatus.RESOLVED_ABSENT, None)
        self._audit_event("RECOVERY", actor, at, {
            "key": key, "action": "recovered", "status": "resolved_absent",
        })
        return resolved
