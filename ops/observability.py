"""Ops observability event builders (OPS-001, ARCHITECTURE.md §8).

Events: backup_started, backup_succeeded, backup_failed, restore_drill.
Each event carries correlation ID, actor alias, unit, action class, record
alias, result, latency, and a redacted error descriptor.

Redaction mirrors the key set used by src/audit/chain.py. The set is
deliberately duplicated here (small, stable) instead of importing the audit
module's private member — ops/ must not couple to src/ internals.
"""
from __future__ import annotations

import math
import unicodedata

# Mirrors _SENSITIVE_KEYS in src/audit/chain.py (keep in sync manually).
# Matching is a case-insensitive SUBSTRING test against each key name, so
# e.g. "DB_Password", "client_secret", "api_key", and "Authorization" are
# all redacted. Substring matching can over-redact (e.g. "monkey" contains
# "key") — that is the deliberate fail-safe direction for an ops log.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {"password", "secret", "token", "key", "credential", "auth", "api_key",
     "authorization"}
)

EVENT_NAMES: frozenset[str] = frozenset(
    {"backup_started", "backup_succeeded", "backup_failed", "restore_drill"}
)

REDACTED = "[REDACTED]"


def _redact_value(value: object) -> object:
    """Recursively redact sensitive values inside dicts and lists.

    Non-JSON-serializable leaf values are sanitized so the final event
    can always be ``json.dumps``-ed (OPS-QA-R2-F-04):
    - ``bytes`` / ``bytearray`` / ``memoryview`` → decoded with
      replacement (falls back to ``repr`` on undecodable prefixes).
    - ``set`` / ``frozenset`` → sorted list of sanitized items.
    - other non-JSON types → ``str(value)``.
    """
    if isinstance(value, dict):
        return {k: _redact_entry(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(v) for v in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    if isinstance(value, (set, frozenset)):
        return sorted(_redact_value(v) for v in value)  # type: ignore[type-var]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _redact_entry(key: object, value: object) -> object:
    # OPS-QA-R2-F-02: normalize unicode homoglyphs (fullwidth, compatibility
    # characters) and casefold before the substring test so a hostile key
    # such as "ｐａｓｓｗｏｒｄ" cannot bypass redaction.
    lowered = unicodedata.normalize("NFKC", str(key)).casefold()
    if any(s in lowered for s in SENSITIVE_KEYS):
        return REDACTED
    return _redact_value(value)


def _reject_multiline(value: str, field: str) -> None:
    """OPS-QA-R2-F-03: event text fields feed JSON-lines log consumers;
    CR/LF would inject forged log lines downstream."""
    if "\n" in value or "\r" in value:
        raise ValueError(f"{field} must be single-line (no CR/LF)")


def _redact(descriptor: dict[str, object] | None) -> dict[str, object] | None:
    if descriptor is None:
        return None
    return {k: _redact_entry(k, v) for k, v in descriptor.items()}


def _event(
    event: str,
    *,
    correlation_id: str,
    actor_alias: str,
    unit: str,
    action_class: str,
    record_alias: str | None,
    result: str,
    latency_ms: float | None,
    error: dict[str, object] | None,
) -> dict[str, object]:
    if event not in EVENT_NAMES:
        raise ValueError(f"unknown ops event {event!r}")
    if not correlation_id:
        raise ValueError("correlation_id is required")
    if not actor_alias:
        raise ValueError("actor_alias is required")
    if not unit:
        raise ValueError("unit is required")
    if not action_class:
        raise ValueError("action_class is required")
    _reject_multiline(correlation_id, "correlation_id")
    _reject_multiline(actor_alias, "actor_alias")
    _reject_multiline(unit, "unit")
    _reject_multiline(action_class, "action_class")
    if record_alias is not None:
        _reject_multiline(record_alias, "record_alias")
    if latency_ms is not None:
        if type(latency_ms) is bool:
            raise ValueError("latency_ms must be a number, not bool")
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("latency_ms must be finite and >= 0")
    return {
        "event": event,
        "correlation_id": correlation_id,
        "actor_alias": actor_alias,
        "unit": unit,
        "action_class": action_class,
        "record_alias": record_alias,
        "result": result,
        "latency_ms": latency_ms,
        "error": _redact(error),
    }


def backup_started(
    *,
    correlation_id: str,
    actor_alias: str,
    unit: str,
    action_class: str,
    record_alias: str | None = None,
) -> dict[str, object]:
    return _event(
        "backup_started",
        correlation_id=correlation_id,
        actor_alias=actor_alias,
        unit=unit,
        action_class=action_class,
        record_alias=record_alias,
        result="started",
        latency_ms=None,
        error=None,
    )


def backup_succeeded(
    *,
    correlation_id: str,
    actor_alias: str,
    unit: str,
    action_class: str,
    record_alias: str | None = None,
    latency_ms: float,
) -> dict[str, object]:
    return _event(
        "backup_succeeded",
        correlation_id=correlation_id,
        actor_alias=actor_alias,
        unit=unit,
        action_class=action_class,
        record_alias=record_alias,
        result="succeeded",
        latency_ms=latency_ms,
        error=None,
    )


def backup_failed(
    *,
    correlation_id: str,
    actor_alias: str,
    unit: str,
    action_class: str,
    record_alias: str | None = None,
    latency_ms: float,
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    return _event(
        "backup_failed",
        correlation_id=correlation_id,
        actor_alias=actor_alias,
        unit=unit,
        action_class=action_class,
        record_alias=record_alias,
        result="failed",
        latency_ms=latency_ms,
        error=error,
    )


def restore_drill(
    *,
    correlation_id: str,
    actor_alias: str,
    unit: str,
    action_class: str,
    record_alias: str | None = None,
    latency_ms: float,
    result: str,
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    if result not in ("succeeded", "failed"):
        raise ValueError("restore_drill result must be 'succeeded' or 'failed'")
    return _event(
        "restore_drill",
        correlation_id=correlation_id,
        actor_alias=actor_alias,
        unit=unit,
        action_class=action_class,
        record_alias=record_alias,
        result=result,
        latency_ms=latency_ms,
        error=error,
    )
