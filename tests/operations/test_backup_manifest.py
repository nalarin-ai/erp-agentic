"""Tests for ops.backup_manifest (OPS-001, slice 1).

Covers schema validation (fail-closed), deterministic canonical hashing,
and tamper detection.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from ops.backup_manifest import (
    BackupManifest,
    InvalidManifest,
    StoreEntry,
    REQUIRED_STORES,
)


def _utc(s: str = "2026-08-15T10:00:00+00:00") -> datetime:
    return datetime.fromisoformat(s)


def _entry(name: str = "erp_db", sha: str = "a" * 64, size: int = 100) -> StoreEntry:
    return StoreEntry(
        name=name,
        artifact_rel_path=f"artifacts/{name}.bin",
        sha256=sha,
        byte_size=size,
    )


def _manifest(**overrides) -> BackupManifest:
    params = {
        "manifest_id": "BKUP-20260815T100000Z-deadbeef",
        "created_at": _utc(),
        "stores": tuple(_entry(n) for n in sorted(REQUIRED_STORES)),
        "rpo_target_seconds": 24 * 3600,
        "rto_target_seconds": 4 * 3600,
    }
    params.update(overrides)
    return BackupManifest(**params)


class TestManifestValidation(unittest.TestCase):
    def test_valid_manifest_builds(self) -> None:
        m = _manifest()
        self.assertEqual(m.manifest_id, "BKUP-20260815T100000Z-deadbeef")
        self.assertEqual(len(m.stores), len(REQUIRED_STORES))

    def test_required_stores_cover_architecture_9(self) -> None:
        # ARCHITECTURE.md §9: ERP database, private files, configuration,
        # custom app, and integration audit state.
        self.assertEqual(
            REQUIRED_STORES,
            frozenset({"erp_db", "erp_private_files", "app_config", "audit_state"}),
        )

    def test_missing_store_is_invalid(self) -> None:
        stores = tuple(_entry(n) for n in sorted(REQUIRED_STORES) if n != "erp_db")
        with self.assertRaises(InvalidManifest):
            _manifest(stores=stores)

    def test_extra_store_is_invalid(self) -> None:
        stores = tuple(_entry(n) for n in sorted(REQUIRED_STORES)) + (_entry("mystery"),)
        with self.assertRaises(InvalidManifest):
            _manifest(stores=stores)

    def test_duplicate_store_is_invalid(self) -> None:
        stores = tuple(_entry(n) for n in sorted(REQUIRED_STORES))[:-1] + (
            _entry("erp_db"),
            _entry("erp_db"),
        )
        with self.assertRaises(InvalidManifest):
            _manifest(stores=stores)

    def test_negative_rpo_is_invalid(self) -> None:
        with self.assertRaises(InvalidManifest):
            _manifest(rpo_target_seconds=-1)

    def test_negative_rto_is_invalid(self) -> None:
        with self.assertRaises(InvalidManifest):
            _manifest(rto_target_seconds=-5)

    def test_naive_created_at_is_invalid(self) -> None:
        with self.assertRaises(InvalidManifest):
            _manifest(created_at=datetime(2026, 8, 15, 10, 0, 0))

    def test_empty_manifest_id_is_invalid(self) -> None:
        with self.assertRaises(InvalidManifest):
            _manifest(manifest_id="")

    def test_bad_sha_is_invalid(self) -> None:
        with self.assertRaises(InvalidManifest):
            _entry(sha="not-a-sha")

    def test_negative_byte_size_is_invalid(self) -> None:
        with self.assertRaises(InvalidManifest):
            _entry(size=-1)


class TestCanonicalSerialization(unittest.TestCase):
    def test_canonical_json_has_sorted_keys(self) -> None:
        m = _manifest()
        text = m.canonical_json()
        parsed = json.loads(text)
        self.assertEqual(list(parsed.keys()), sorted(parsed.keys()))
        # canonical: no whitespace noise
        self.assertNotIn("\n", text)

    def test_canonical_json_is_deterministic(self) -> None:
        m1 = _manifest()
        m2 = _manifest()
        self.assertEqual(m1.canonical_json(), m2.canonical_json())

    def test_manifest_hash_excludes_created_at_and_id(self) -> None:
        """Hash binds content (stores + targets), not the creation timestamp."""
        m1 = _manifest()
        m2 = _manifest(
            created_at=_utc("2027-01-01T00:00:00+00:00"),
            manifest_id="BKUP-20270101T000000Z-00000000",
        )
        self.assertEqual(m1.manifest_hash(), m2.manifest_hash())

    def test_manifest_hash_changes_with_content(self) -> None:
        m1 = _manifest()
        m2 = _manifest(rpo_target_seconds=60)
        self.assertNotEqual(m1.manifest_hash(), m2.manifest_hash())

    def test_manifest_hash_format(self) -> None:
        h = _manifest().manifest_hash()
        self.assertTrue(h.startswith("sha256:"))
        self.assertEqual(len(h), 71)

    def test_store_entry_new_fields_default_and_serialize(self) -> None:
        """OPS-QA-R1-F-01: allow_empty/empty/source default off and serialize."""
        e = _entry()
        self.assertFalse(e.allow_empty)
        self.assertFalse(e.empty)
        self.assertIsNone(e.source)
        d = e.to_dict()
        self.assertEqual(d["allow_empty"], False)
        self.assertEqual(d["empty"], False)
        self.assertIsNone(d["source"])
        # Round-trip preserves the flags.
        e2 = StoreEntry.from_dict(d)
        self.assertFalse(e2.allow_empty)

    def test_store_entry_empty_requires_allow_empty(self) -> None:
        with self.assertRaises(InvalidManifest):
            StoreEntry(
                name="erp_db",
                artifact_rel_path="artifacts/erp_db.bin",
                sha256="a" * 64,
                byte_size=0,
                empty=True,
                allow_empty=False,
            )
        ok = StoreEntry(
            name="erp_db",
            artifact_rel_path="artifacts/erp_db.bin",
            sha256="a" * 64,
            byte_size=0,
            empty=True,
            allow_empty=True,
            source="pilot",
        )
        self.assertTrue(ok.empty)

    def test_store_entry_bad_source_rejected(self) -> None:
        with self.assertRaises(InvalidManifest):
            StoreEntry(
                name="erp_db",
                artifact_rel_path="artifacts/erp_db.bin",
                sha256="a" * 64,
                byte_size=1,
                source="nowhere",
            )

    def test_from_json_rejects_unknown_top_level_fields(self) -> None:
        """OPS-QA-R1-F-07: unknown top-level fields must not pass silently."""
        m = _manifest()
        data = json.loads(m.canonical_json())
        data["unexpected_field"] = "surprise"
        with self.assertRaises(InvalidManifest) as ctx:
            BackupManifest.from_json(json.dumps(data))
        self.assertIn("unexpected_field", str(ctx.exception))

    def test_from_json_rejects_unknown_store_entry_fields(self) -> None:
        m = _manifest()
        data = json.loads(m.canonical_json())
        data["stores"][0]["mystery"] = 1
        with self.assertRaises(InvalidManifest) as ctx:
            BackupManifest.from_json(json.dumps(data))
        self.assertIn("mystery", str(ctx.exception))

    def test_round_trip_from_json(self) -> None:
        m = _manifest()
        m2 = BackupManifest.from_json(m.canonical_json())
        self.assertEqual(m.manifest_hash(), m2.manifest_hash())
        self.assertEqual(m.manifest_id, m2.manifest_id)

    def test_from_json_non_numeric_rpo_rto_raise_invalid_manifest(self) -> None:
        """OPS-QA-R2-F-02: raw int() on rpo/rto must surface as InvalidManifest."""
        for field in ("rpo_target_seconds", "rto_target_seconds"):
            data = json.loads(_manifest().canonical_json())
            data[field] = "not-a-number"
            with self.assertRaises(InvalidManifest, msg=f"{field} accepted str") as ctx:
                BackupManifest.from_json(json.dumps(data))
            self.assertIn(field, str(ctx.exception))

    def test_store_entry_from_dict_non_numeric_byte_size_raises_invalid_manifest(self) -> None:
        """OPS-QA-R2-F-02: byte_size int() must surface as InvalidManifest."""
        entry = _entry().to_dict()
        entry["byte_size"] = "x"
        with self.assertRaises(InvalidManifest) as ctx:
            StoreEntry.from_dict(entry)
        self.assertIn("byte_size", str(ctx.exception))


class TestTamperDetection(unittest.TestCase):
    def test_flipped_artifact_hash_detected_by_verify(self) -> None:
        import hashlib

        m = _manifest()
        # A good artifact matches; a tampered one must not.
        good = hashlib.sha256(b"payload").hexdigest()
        entry = next(s for s in m.stores if s.name == "erp_db")
        good_entry = StoreEntry(entry.name, entry.artifact_rel_path, good, 7)
        m_ok = _manifest(stores=tuple(
            good_entry if s.name == "erp_db" else s for s in m.stores
        ))
        self.assertTrue(m_ok.verify_artifact("erp_db", b"payload"))
        self.assertFalse(m_ok.verify_artifact("erp_db", b"payloae"))

    def test_unknown_store_verify_is_fail_closed(self) -> None:
        m = _manifest()
        with self.assertRaises(InvalidManifest):
            m.verify_artifact("nope", b"x")


class TestArtifactRelPathSafety(unittest.TestCase):
    """OPS-QA-R2-F-01: artifact_rel_path must be a safe relative path."""

    def test_absolute_artifact_rel_path_rejected(self) -> None:
        with self.assertRaises(InvalidManifest) as ctx:
            StoreEntry(
                name="erp_db",
                artifact_rel_path="/etc/passwd",
                sha256="a" * 64,
                byte_size=1,
            )
        self.assertIn("artifact_rel_path", str(ctx.exception))

    def test_dotdot_artifact_rel_path_rejected(self) -> None:
        with self.assertRaises(InvalidManifest) as ctx:
            StoreEntry(
                name="erp_db",
                artifact_rel_path="../../etc/evil",
                sha256="a" * 64,
                byte_size=1,
            )
        self.assertIn("artifact_rel_path", str(ctx.exception))

    def test_from_dict_dotdot_artifact_rel_path_rejected(self) -> None:
        entry = _entry().to_dict()
        entry["artifact_rel_path"] = "../escape.tar.gz"
        with self.assertRaises(InvalidManifest) as ctx:
            StoreEntry.from_dict(entry)
        self.assertIn("artifact_rel_path", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
