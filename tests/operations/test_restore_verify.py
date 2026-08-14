"""Tests for scripts.backup.restore_verify (OPS-001, slice 3).

Covers the restore round-trip against fixture backups, plus failure
injection: corrupted artifact bytes, truncated archives, manifest/artifact
mismatch, and missing reconciliation data.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _backup(out: Path, fixture_root: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "scripts.backup.backup_run",
           "--mode", "fixture", "--out", str(out)]
    if fixture_root is not None:
        cmd += ["--fixture-root", str(fixture_root)]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"backup failed: {result.stderr}")
    return result


def _restore(manifest: Path, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.backup.restore_verify",
         "--manifest", str(manifest), "--target", str(target)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )


class TestRestoreRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ops-restore-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.backup_dir = self.tmp / "backup"
        _backup(self.backup_dir)
        self.manifest = self.backup_dir / "manifest.json"
        self.target = self.tmp / "restored"

    def test_round_trip_restore_ok(self) -> None:
        result = _restore(self.manifest, self.target)
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        self.assertIn("RESTORE_OK", result.stdout)

    def test_round_trip_reports_all_checks(self) -> None:
        result = _restore(self.manifest, self.target)
        out = result.stdout
        for store in ("erp_db", "erp_private_files", "app_config", "audit_state"):
            self.assertIn(f"checksum:{store}", out)
        for check in ("record_counts", "audit_head", "config_version"):
            self.assertIn(f"check:{check}", out)

    def test_restored_bytes_equal_source_bytes(self) -> None:
        result = _restore(self.manifest, self.target)
        self.assertEqual(result.returncode, 0)
        for store in ("erp_db", "erp_private_files", "app_config", "audit_state"):
            src_dir = FIXTURES / store
            dst_dir = self.target / store
            for path in sorted(src_dir.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(src_dir)
                    restored = dst_dir / rel
                    self.assertTrue(restored.is_file(), f"missing {restored}")
                    self.assertEqual(restored.read_bytes(), path.read_bytes(),
                                     f"byte mismatch: {store}/{rel}")


class TestRestoreFailureInjection(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ops-restore-fail-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.backup_dir = self.tmp / "backup"
        _backup(self.backup_dir)
        self.manifest = self.backup_dir / "manifest.json"
        self.target = self.tmp / "restored"

    def test_corrupted_artifact_byte_fails_and_names_store(self) -> None:
        artifact = self.backup_dir / "artifacts" / "erp_db.tar.gz"
        data = bytearray(artifact.read_bytes())
        data[-2] ^= 0xFF  # flip a content byte near the end
        artifact.write_bytes(bytes(data))
        result = _restore(self.manifest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)
        self.assertIn("erp_db", result.stdout + result.stderr)

    def test_truncated_archive_fails(self) -> None:
        artifact = self.backup_dir / "artifacts" / "erp_private_files.tar.gz"
        data = artifact.read_bytes()
        artifact.write_bytes(data[: len(data) // 2])
        result = _restore(self.manifest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)
        self.assertIn("erp_private_files", result.stdout + result.stderr)

    def test_manifest_artifact_mismatch_fails(self) -> None:
        # Swap two artifacts on disk: manifest hashes no longer match names.
        a = self.backup_dir / "artifacts" / "erp_db.tar.gz"
        b = self.backup_dir / "artifacts" / "app_config.tar.gz"
        tmp_swap = self.tmp / "swap"
        shutil.move(a, tmp_swap)
        shutil.move(b, a)
        shutil.move(tmp_swap, b)
        result = _restore(self.manifest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)

    def test_missing_reconciliation_file_fails_naming_check(self) -> None:
        # Rebuild a fixture missing record_counts.json inside audit_state.
        broken = self.tmp / "fixtures-broken"
        shutil.copytree(FIXTURES, broken)
        (broken / "audit_state" / "record_counts.json").unlink()
        backup2 = self.tmp / "backup2"
        _backup(backup2, fixture_root=broken)
        result = _restore(backup2 / "manifest.json", self.tmp / "restored2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)
        self.assertIn("record_counts", result.stdout + result.stderr)

    def test_empty_artifact_with_allow_empty_restores_ok(self) -> None:
        """OPS-QA-R1-F-01: manifest allow_empty + empty artifact → OK."""
        import hashlib

        # Repack erp_private_files as a genuinely empty tar.
        artifact = self.backup_dir / "artifacts" / "erp_private_files.tar.gz"
        with tarfile.open(artifact, "w:gz") as tf:
            pass
        data = artifact.read_bytes()
        manifest_data = json.loads(self.manifest.read_text(encoding="utf-8"))
        for s in manifest_data["stores"]:
            if s["name"] == "erp_private_files":
                s["sha256"] = hashlib.sha256(data).hexdigest()
                s["byte_size"] = len(data)
                s["allow_empty"] = True
                s["empty"] = True
        self.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
        result = _restore(self.manifest, self.target)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("RESTORE_OK", result.stdout)
        self.assertIn("erp_private_files", result.stdout)

    def test_empty_artifact_without_allow_empty_fails_naming_store(self) -> None:
        """OPS-QA-R1-F-01: empty artifact without the contract stays FAIL."""
        import hashlib

        artifact = self.backup_dir / "artifacts" / "erp_private_files.tar.gz"
        with tarfile.open(artifact, "w:gz") as tf:
            pass
        data = artifact.read_bytes()
        manifest_data = json.loads(self.manifest.read_text(encoding="utf-8"))
        for s in manifest_data["stores"]:
            if s["name"] == "erp_private_files":
                s["sha256"] = hashlib.sha256(data).hexdigest()
                s["byte_size"] = len(data)
                # allow_empty stays False / empty stays False
        self.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
        result = _restore(self.manifest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)
        self.assertIn("erp_private_files", result.stdout + result.stderr)

    def test_byte_size_mismatch_fails_even_with_correct_sha(self) -> None:
        """OPS-QA-R1-F-08: pin the byte_size comparison branch directly."""
        artifact = self.backup_dir / "artifacts" / "erp_db.tar.gz"
        data = artifact.read_bytes()
        manifest_data = json.loads(self.manifest.read_text(encoding="utf-8"))
        for s in manifest_data["stores"]:
            if s["name"] == "erp_db":
                # sha stays correct for the content; byte_size is wrong.
                s["byte_size"] = len(data) + 1
        self.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
        result = _restore(self.manifest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)
        self.assertIn("erp_db", result.stdout + result.stderr)
        self.assertIn("size", result.stdout.lower())

    def test_nonempty_artifact_with_empty_markers_fails_naming_store(self) -> None:
        """OPS-QA-R2-F-01: allow_empty+empty but archive has files → fail closed."""
        manifest_data = json.loads(self.manifest.read_text(encoding="utf-8"))
        for s in manifest_data["stores"]:
            if s["name"] == "erp_private_files":
                s["allow_empty"] = True
                s["empty"] = True
        self.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
        result = _restore(self.manifest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)
        self.assertIn("erp_private_files", result.stdout + result.stderr)
        self.assertIn("empty", result.stdout + result.stderr)

    def test_pilot_shape_record_counts_restores_ok(self) -> None:
        """Mutant (d): restore-level pilot-shape record_counts must pass provenance branch."""
        # Build a pilot-shape fixture root: audit_state/record_counts.json has
        # {"source":"pilot","tables":{...}} and audit_head.txt is sha256 of that file.
        import hashlib

        pilot_root = self.tmp / "fixtures-pilot"
        shutil.copytree(FIXTURES, pilot_root)

        record_counts = pilot_root / "audit_state" / "record_counts.json"
        record_counts.write_text(
            json.dumps({"source": "pilot", "tables": {"tabSales Invoice": 3, "tabCustomer": 2}}),
            encoding="utf-8",
        )
        audit_head = pilot_root / "audit_state" / "audit_head.txt"
        audit_head.write_text(
            "sha256:" + hashlib.sha256(record_counts.read_bytes()).hexdigest(),
            encoding="utf-8",
        )

        backup2 = self.tmp / "backup-pilot"
        _backup(backup2, fixture_root=pilot_root)

        # Mark all stores as pilot provenance in the manifest.
        manifest2 = backup2 / "manifest.json"
        manifest_data = json.loads(manifest2.read_text(encoding="utf-8"))
        for s in manifest_data["stores"]:
            s["source"] = "pilot"
        manifest2.write_text(json.dumps(manifest_data), encoding="utf-8")

        result = _restore(manifest2, self.tmp / "restored-pilot")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("check:record_counts pilot capture", result.stdout)
        self.assertIn("RESTORE_OK", result.stdout)

    def test_missing_manifest_fails(self) -> None:
        result = _restore(self.tmp / "no-such-manifest.json", self.target)
        self.assertNotEqual(result.returncode, 0)

    def test_missing_artifact_file_fails(self) -> None:
        (self.backup_dir / "artifacts" / "audit_state.tar.gz").unlink()
        result = _restore(self.manifest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audit_state", result.stdout + result.stderr)

    def test_manifest_with_traversal_artifact_path_fails(self) -> None:
        """OPS-QA-R2-F-01: hostile manifest must not steer the verifier
        into reading files outside the backup directory."""
        secret = self.tmp / "host-secret.txt"
        secret.write_text("do-not-read-me", encoding="utf-8")
        manifest_data = json.loads(self.manifest.read_text(encoding="utf-8"))
        import hashlib

        digest = hashlib.sha256(b"do-not-read-me").hexdigest()
        for s in manifest_data["stores"]:
            if s["name"] == "audit_state":
                s["artifact_rel_path"] = "../host-secret.txt"
                s["sha256"] = digest
                s["byte_size"] = len(b"do-not-read-me")
        self.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
        result = _restore(self.manifest, self.tmp / "restored-trav")
        self.assertNotEqual(result.returncode, 0)
        # The verifier must reject the path, not silently read+match it.
        self.assertNotIn("RESTORE_OK", result.stdout)

    def test_schema_bypassed_manifest_still_blocked_by_containment_guard(self) -> None:
        """OPS-QA-R3-F-01 (M2 survivor): the defense-in-depth resolve()
        containment guard in restore_verify._verify_artifact must reject an
        escaping artifact path even when the StoreEntry schema guard is
        bypassed entirely (manifest object built via object.__new__)."""
        import hashlib

        from ops.backup_manifest import BackupManifest, StoreEntry
        from scripts.backup.restore_verify import CheckLog, _verify_artifact

        secret = self.tmp / "host-secret.txt"
        payload = b"do-not-read-me"
        secret.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()

        entry = StoreEntry(
            name="audit_state",
            artifact_rel_path="artifacts/audit_state.tar.gz",
            sha256=digest,
            byte_size=len(payload),
        )
        # Bypass __post_init__ (and its path guard) entirely.
        evil = object.__new__(StoreEntry)
        object.__setattr__(evil, "name", "audit_state")
        object.__setattr__(evil, "artifact_rel_path", "../host-secret.txt")
        object.__setattr__(evil, "sha256", digest)
        object.__setattr__(evil, "byte_size", len(payload))
        object.__setattr__(evil, "allow_empty", False)
        object.__setattr__(evil, "empty", False)
        object.__setattr__(evil, "source", None)

        manifest_data = json.loads(self.manifest.read_text(encoding="utf-8"))
        stores = tuple(
            StoreEntry(
                name=s["name"],
                artifact_rel_path=s["artifact_rel_path"],
                sha256=s["sha256"],
                byte_size=s["byte_size"],
                allow_empty=s.get("allow_empty", False),
                empty=s.get("empty", False),
                source=s.get("source"),
            )
            for s in manifest_data["stores"]
        )
        stores = tuple(evil if s.name == "audit_state" else s for s in stores)
        manifest = BackupManifest(
            manifest_id=manifest_data["manifest_id"],
            created_at=__import__("datetime").datetime.fromisoformat(
                manifest_data["created_at"]
            ),
            stores=stores,
            rpo_target_seconds=manifest_data["rpo_target_seconds"],
            rto_target_seconds=manifest_data["rto_target_seconds"],
        )
        self.assertIs(manifest.store_entry("audit_state"), evil)

        log = CheckLog()
        result = _verify_artifact(manifest, self.backup_dir, "audit_state", log)
        self.assertIsNone(result)
        self.assertIn("checksum:audit_state", log.failures)
        # Control: a well-formed entry for the same store still verifies.
        good_manifest = BackupManifest(
            manifest_id=manifest_data["manifest_id"],
            created_at=__import__("datetime").datetime.fromisoformat(
                manifest_data["created_at"]
            ),
            stores=tuple(
                entry if s.name == "audit_state" else s for s in stores
            ),
            rpo_target_seconds=manifest_data["rpo_target_seconds"],
            rto_target_seconds=manifest_data["rto_target_seconds"],
        )
        # The control entry's digest matches the real artifact bytes only if
        # we hash the real artifact; simpler: verify against a manifest whose
        # audit_state entry is the original one from disk.
        real_manifest_data = json.loads(self.manifest.read_text(encoding="utf-8"))
        real_entry = next(
            s for s in real_manifest_data["stores"] if s["name"] == "audit_state"
        )
        real_store = StoreEntry(
            name=real_entry["name"],
            artifact_rel_path=real_entry["artifact_rel_path"],
            sha256=real_entry["sha256"],
            byte_size=real_entry["byte_size"],
            allow_empty=real_entry.get("allow_empty", False),
            empty=real_entry.get("empty", False),
            source=real_entry.get("source"),
        )
        good_stores = tuple(
            real_store if s.name == "audit_state" else s for s in stores
        )
        good_manifest = BackupManifest(
            manifest_id=manifest_data["manifest_id"],
            created_at=__import__("datetime").datetime.fromisoformat(
                manifest_data["created_at"]
            ),
            stores=good_stores,
            rpo_target_seconds=manifest_data["rpo_target_seconds"],
            rto_target_seconds=manifest_data["rto_target_seconds"],
        )
        log2 = CheckLog()
        result2 = _verify_artifact(good_manifest, self.backup_dir, "audit_state", log2)
        self.assertIsNotNone(result2)
        self.assertEqual(log2.failures, [])


if __name__ == "__main__":
    unittest.main()
