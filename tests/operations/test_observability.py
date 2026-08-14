"""Tests for ops.observability (OPS-001, slice 4).

Event schema per ARCHITECTURE.md §8: correlation ID, actor alias, unit,
action class, record alias, result, latency, redacted error descriptor.
"""
from __future__ import annotations

import time
import unittest

from ops.observability import (
    backup_failed,
    backup_started,
    backup_succeeded,
    restore_drill,
    EVENT_NAMES,
)


class TestEventSchema(unittest.TestCase):
    def test_event_names_cover_ops_events(self) -> None:
        self.assertEqual(
            EVENT_NAMES,
            frozenset({
                "backup_started",
                "backup_succeeded",
                "backup_failed",
                "restore_drill",
            }),
        )

    def test_backup_started_schema(self) -> None:
        ev = backup_started(
            correlation_id="corr-1",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="backup",
            record_alias="BKUP-X",
        )
        for key in (
            "event", "correlation_id", "actor_alias", "unit",
            "action_class", "record_alias", "result", "latency_ms", "error",
        ):
            self.assertIn(key, ev, f"missing key {key}")
        self.assertEqual(ev["event"], "backup_started")
        self.assertEqual(ev["result"], "started")
        self.assertIsNone(ev["error"])

    def test_backup_succeeded_carries_latency(self) -> None:
        ev = backup_succeeded(
            correlation_id="corr-2",
            actor_alias="ops-bot",
            unit="UNIT-KRW",
            action_class="backup",
            record_alias="BKUP-Y",
            latency_ms=123.4,
        )
        self.assertEqual(ev["event"], "backup_succeeded")
        self.assertEqual(ev["result"], "succeeded")
        self.assertAlmostEqual(ev["latency_ms"], 123.4)

    def test_backup_failed_redacts_sensitive_error_descriptor(self) -> None:
        ev = backup_failed(
            correlation_id="corr-3",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="backup",
            record_alias="BKUP-Z",
            latency_ms=5.0,
            error={
                "message": "dump failed",
                "password": "supersecret-value",
                "token": "abc123",
                "detail": "exit 1",
            },
        )
        self.assertEqual(ev["event"], "backup_failed")
        self.assertEqual(ev["result"], "failed")
        err = ev["error"]
        assert err is not None
        self.assertEqual(err["password"], "[REDACTED]")
        self.assertEqual(err["token"], "[REDACTED]")
        self.assertEqual(err["message"], "dump failed")
        self.assertEqual(err["detail"], "exit 1")
        # Leak check on serialized form.
        import json

        text = json.dumps(ev)
        self.assertNotIn("supersecret-value", text)
        self.assertNotIn("abc123", text)

    def test_redaction_is_recursive_and_substring_case_insensitive(self) -> None:
        """OPS-QA-R1-F-04: nested dicts/lists and substring key matches."""
        ev = backup_failed(
            correlation_id="corr-r4",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="backup",
            record_alias="BKUP-R",
            latency_ms=1.0,
            error={
                "message": "dump failed",
                "nested": {
                    "DB_Password": "p@ss-nested",
                    "inner": [{"api_key": "key-123"}, {"note": "ok"}],
                },
                "headers": {"Authorization": "Bearer tok-xyz"},
                "items": [{"client_secret": "shh"}, "plain-string"],
                "benign": "keepme",
            },
        )
        import json

        text = json.dumps(ev)
        for leaked in ("p@ss-nested", "key-123", "tok-xyz", "shh"):
            self.assertNotIn(leaked, text)
        err = ev["error"]
        assert err is not None
        nested = err["nested"]
        assert isinstance(nested, dict)
        self.assertEqual(nested["DB_Password"], "[REDACTED]")
        self.assertEqual(nested["inner"][0]["api_key"], "[REDACTED]")
        self.assertEqual(nested["inner"][1]["note"], "ok")
        headers = err["headers"]
        assert isinstance(headers, dict)
        self.assertEqual(headers["Authorization"], "[REDACTED]")
        items = err["items"]
        assert isinstance(items, list)
        self.assertEqual(items[0]["client_secret"], "[REDACTED]")
        self.assertEqual(items[1], "plain-string")
        self.assertEqual(err["benign"], "keepme")
        self.assertEqual(err["message"], "dump failed")

    def test_restore_drill_event(self) -> None:
        ev = restore_drill(
            correlation_id="corr-4",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="restore",
            record_alias="BKUP-W",
            latency_ms=900.0,
            result="succeeded",
        )
        self.assertEqual(ev["event"], "restore_drill")
        self.assertEqual(ev["result"], "succeeded")

    def test_validation_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            backup_started(
                correlation_id="",
                actor_alias="ops-bot",
                unit="UNIT-BM",
                action_class="backup",
                record_alias="BKUP-1",
            )
        with self.assertRaises(ValueError):
            backup_succeeded(
                correlation_id="c",
                actor_alias="ops-bot",
                unit="UNIT-BM",
                action_class="backup",
                record_alias="BKUP-1",
                latency_ms=-1.0,
            )

    def test_latency_non_finite_or_negative_rejected(self) -> None:
        """OPS-QA-R1-F-05: NaN/inf latency would emit invalid JSON."""
        import math

        for bad in (math.nan, math.inf, -math.inf, -0.001):
            with self.assertRaises(ValueError, msg=f"latency {bad} accepted"):
                backup_succeeded(
                    correlation_id="c",
                    actor_alias="ops-bot",
                    unit="UNIT-BM",
                    action_class="backup",
                    record_alias="BKUP-BAD",
                    latency_ms=bad,
                )
            with self.assertRaises(ValueError, msg=f"latency {bad} accepted"):
                restore_drill(
                    correlation_id="c",
                    actor_alias="ops-bot",
                    unit="UNIT-BM",
                    action_class="restore",
                    latency_ms=bad,
                    result="failed",
                )

    def test_error_descriptor_bytes_and_exotic_types_serialize(self) -> None:
        """OPS-QA-R2-F-04: bytes / non-JSON types inside error must not TypeError."""
        ev = backup_failed(
            correlation_id="corr-bytes",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="backup",
            record_alias="BKUP-BYTES",
            latency_ms=1.0,
            error={
                "message": "dump failed",
                "payload": b"\x00\xff binary",
                "nested": {"deep": [{"raw": b"\x89PNG"}, ("a", b"b"), {1, 2}]},
            },
        )
        import json

        text = json.dumps(ev)  # must not raise TypeError
        self.assertIn("payload", text)
        self.assertIn("raw", text)

    def test_latency_bool_rejected(self) -> None:
        """OPS-QA-R2-F-03: bool is not a valid latency even though isfinite(True)."""
        for bad in (True, False):
            with self.assertRaises(ValueError, msg=f"latency {bad} accepted"):
                backup_succeeded(
                    correlation_id="c",
                    actor_alias="ops-bot",
                    unit="UNIT-BM",
                    action_class="backup",
                    record_alias="BKUP-BOOL",
                    latency_ms=bad,
                )
            with self.assertRaises(ValueError, msg=f"latency {bad} accepted"):
                restore_drill(
                    correlation_id="c",
                    actor_alias="ops-bot",
                    unit="UNIT-BM",
                    action_class="restore",
                    latency_ms=bad,
                    result="failed",
                )

    def test_latency_negative_zero_still_accepted(self) -> None:
        """OPS-QA-R2-F-03: -0.0 is finite and >= 0; it must keep passing."""
        ev = backup_succeeded(
            correlation_id="c",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="backup",
            record_alias="BKUP-NEGZERO",
            latency_ms=-0.0,
        )
        self.assertEqual(ev["latency_ms"], -0.0)

    def test_event_serializes_with_strict_json(self) -> None:
        import json

        ev = backup_succeeded(
            correlation_id="c",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="backup",
            record_alias="BKUP-J",
            latency_ms=1.5,
        )
        text = json.dumps(ev, allow_nan=False)
        self.assertIn('"latency_ms": 1.5', text)

    def test_latency_is_measurable_and_monotonic_sane(self) -> None:
        start = time.perf_counter()
        time.sleep(0.001)
        latency = (time.perf_counter() - start) * 1000.0
        ev = backup_succeeded(
            correlation_id="corr-5",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="backup",
            record_alias="BKUP-L",
            latency_ms=latency,
        )
        self.assertGreaterEqual(ev["latency_ms"], 1.0)
        self.assertLess(ev["latency_ms"], 60_000.0)

    def test_redaction_unicode_homoglyph_keys_normalized(self) -> None:
        """OPS-QA-R2-F-02: NFKC + casefold before substring redaction."""
        import json

        ev = backup_failed(
            correlation_id="corr-u1",
            actor_alias="ops-bot",
            unit="UNIT-BM",
            action_class="backup",
            latency_ms=1.0,
            error={
                "ｐａｓｓｗｏｒｄ": "fullwidth-secret",  # fullwidth latin
                "ＡＰＩ_ＫＥＹ": "caps-fullwidth-secret",  # fullwidth uppercase
                "note": "still-visible",
            },
        )
        text = json.dumps(ev, ensure_ascii=False)
        for leaked in ("fullwidth-secret", "caps-fullwidth-secret"):
            self.assertNotIn(leaked, text)
        self.assertIn("still-visible", text)

    def test_event_text_fields_reject_newlines(self) -> None:
        """OPS-QA-R2-F-03: JSON-lines consumers must not get log injection."""
        with self.assertRaises(ValueError):
            backup_started(
                correlation_id="abc\nINJECTED",
                actor_alias="ops-bot",
                unit="UNIT-BM",
                action_class="backup",
            )
        with self.assertRaises(ValueError):
            backup_started(
                correlation_id="corr-ok",
                actor_alias="ops-bot",
                unit="UNIT-BM\r\nFORGED",
                action_class="backup",
            )


if __name__ == "__main__":
    unittest.main()
