"""MVP-AC-10: export / backup / isolated restore (OPS-001).

Criteria (TRACEABILITY_MATRIX.md section D): corrupt or inconsistent backup
sets are rejected; restore works only into an isolated target; pilot/live
mode is guarded.

This suite drives the REAL tooling as subprocesses
(``python3 -m scripts.backup.backup_run`` / ``scripts.backup.restore_verify``)
against a SYNTHETIC fixture store tree built in a tmp dir (pattern from
tests/operations/test_backup_run.py). It never touches pilot containers or
live data.

Scenarios:
1. Fixture-mode backup produces a complete manifest (all REQUIRED_STORES)
   with valid sha256 checksums for every artifact.
2. Restore-verify into an isolated target directory succeeds (RESTORE_OK).
3. Corrupt / missing / inconsistent manifest or artifacts are rejected with
   a non-zero exit and no partial restore.
4. Pilot/live mode refuses to run without the acknowledgement flag (and,
   defense-in-depth, refuses while pilot containers are absent).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ops.backup_manifest import BackupManifest, REQUIRED_STORES

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_backup(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.backup.backup_run", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )


def _run_restore(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.backup.restore_verify", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )


def _build_synthetic_fixture_root(root: Path) -> None:
    """One self-contained synthetic store tree (all four required stores).

    Bytes are synthetic only; the record-count marker is consistent across
    the DB dump and audit_state so restore reconciliation passes.
    """
    (root / "erp_db").mkdir(parents=True)
    (root / "erp_db" / "dump.sql").write_text(
        "-- SYNTHETIC PILOT EVIDENCE FIXTURE ONLY.\n"
        "CREATE TABLE `tabSynthetic` (`name` varchar(64));\n"
        "INSERT INTO `tabSynthetic` VALUES ('SYN-A'), ('SYN-B'), ('SYN-C');\n"
        "-- fixture-record-count: 3\n",
        encoding="utf-8",
    )
    (root / "erp_private_files" / "private").mkdir(parents=True)
    (root / "erp_private_files" / "private" / "syn-note.txt").write_text(
        "synthetic private file payload\n", encoding="utf-8",
    )
    (root / "app_config").mkdir(parents=True)
    (root / "app_config" / "site_config.json").write_text(
        json.dumps({"db_name": "syn_db", "config_version": "syncfg-1"}) + "\n",
        encoding="utf-8",
    )
    (root / "app_config" / "config_version.txt").write_text(
        "syncfg-1\n", encoding="utf-8",
    )
    (root / "audit_state").mkdir(parents=True)
    (root / "audit_state" / "record_counts.json").write_text(
        json.dumps({"audit_records": 3, "erp_db_rows": 3,
                    "outbox_pending": 0}) + "\n",
        encoding="utf-8",
    )
    (root / "audit_state" / "audit_head.txt").write_text(
        "sha256:" + hashlib.sha256(b"synthetic-audit-head").hexdigest() + "\n",
        encoding="utf-8",
    )


class TestAc10BackupRestore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pilot-ac10-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fixture_root = self.tmp / "fixture-stores"
        _build_synthetic_fixture_root(self.fixture_root)
        self.out = self.tmp / "backup-out"
        self.target = self.tmp / "restore-target"

    def _backup_ok(self) -> subprocess.CompletedProcess[str]:
        result = _run_backup(
            "--mode", "fixture",
            "--fixture-root", str(self.fixture_root),
            "--out", str(self.out),
        )
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr + result.stdout)
        self.assertIn("BACKUP_OK", result.stdout)
        return result

    # -- 1. manifest completeness + checksums --------------------------------------

    def test_fixture_backup_manifest_complete_and_checksums_valid(self) -> None:
        self._backup_ok()
        manifest = BackupManifest.from_json(
            (self.out / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual({s.name for s in manifest.stores}, set(REQUIRED_STORES))
        self.assertTrue(manifest.manifest_id.startswith("BKUP-"))
        self.assertEqual(manifest.encryption, "none")
        for store in manifest.stores:
            artifact = self.out / store.artifact_rel_path
            self.assertTrue(artifact.is_file(), f"missing {artifact}")
            data = artifact.read_bytes()
            self.assertEqual(len(data), store.byte_size)
            self.assertEqual(hashlib.sha256(data).hexdigest(), store.sha256)
            self.assertEqual(store.source, "fixture")
        # SHA256SUMS agrees with the manifest.
        sums = (self.out / "SHA256SUMS").read_text(encoding="utf-8")
        for store in manifest.stores:
            self.assertIn(store.sha256, sums)

    # -- 2. isolated restore succeeds ---------------------------------------------------

    def test_restore_verify_into_isolated_target_succeeds(self) -> None:
        self._backup_ok()
        result = _run_restore(
            "--manifest", str(self.out / "manifest.json"),
            "--target", str(self.target),
        )
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr + result.stdout)
        self.assertIn("RESTORE_OK", result.stdout)
        # All four stores extracted into the isolated target; the restored
        # DB dump matches the synthetic source byte-for-byte.
        for store in REQUIRED_STORES:
            self.assertTrue((self.target / store).is_dir())
        self.assertEqual(
            (self.target / "erp_db" / "dump.sql").read_bytes(),
            (self.fixture_root / "erp_db" / "dump.sql").read_bytes(),
        )

    # -- 3. corrupt / missing / inconsistent sets are rejected ----------------------------

    def test_missing_manifest_rejected(self) -> None:
        result = _run_restore(
            "--manifest", str(self.tmp / "no-such-manifest.json"),
            "--target", str(self.target),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)

    def test_corrupt_manifest_json_rejected(self) -> None:
        self._backup_ok()
        (self.out / "manifest.json").write_text("{ not json", encoding="utf-8")
        result = _run_restore(
            "--manifest", str(self.out / "manifest.json"),
            "--target", str(self.target),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)

    def test_tampered_artifact_rejected_by_checksum(self) -> None:
        self._backup_ok()
        artifact = self.out / "artifacts" / "erp_db.tar.gz"
        artifact.write_bytes(b"tampered synthetic payload")
        result = _run_restore(
            "--manifest", str(self.out / "manifest.json"),
            "--target", str(self.target),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum:erp_db", result.stdout)
        self.assertIn("RESTORE_FAIL", result.stdout)

    def test_inconsistent_manifest_missing_store_rejected(self) -> None:
        """A manifest that drops a required store is invalid at load time."""
        self._backup_ok()
        raw = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        raw["stores"] = [s for s in raw["stores"] if s["name"] != "audit_state"]
        (self.out / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
        result = _run_restore(
            "--manifest", str(self.out / "manifest.json"),
            "--target", str(self.target),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESTORE_FAIL", result.stdout)

    def test_missing_fixture_store_fails_backup_with_no_partial_manifest(self) -> None:
        shutil.rmtree(self.fixture_root / "audit_state")
        result = _run_backup(
            "--mode", "fixture",
            "--fixture-root", str(self.fixture_root),
            "--out", str(self.out),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audit_state", result.stderr + result.stdout)
        self.assertFalse((self.out / "manifest.json").exists())

    # -- 4. pilot/live mode guard ------------------------------------------------------------

    def test_pilot_mode_refuses_without_acknowledgement_flag(self) -> None:
        result = _run_backup("--mode", "pilot", "--out", str(self.tmp / "o"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("--i-understand-local-only", result.stderr)
        self.assertFalse((self.tmp / "o" / "manifest.json").exists())

    def test_pilot_mode_refuses_when_containers_absent(self) -> None:
        ps = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=15,
        )
        if ps.returncode == 0 and "erpnext-pilot-db" in ps.stdout.splitlines():
            self.skipTest("pilot db container is up; guard would not trigger")
        result = _run_backup(
            "--mode", "pilot", "--i-understand-local-only",
            "--out", str(self.tmp / "o2"),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("erpnext-pilot-db", result.stderr)
        self.assertFalse((self.tmp / "o2" / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
