"""Tests for scripts.backup.backup_run (OPS-001, slice 2).

Fixture mode is exercised end-to-end for real (subprocess invocation of
``python3 -m scripts.backup.backup_run``). Pilot mode is guarded: it must
refuse without the acknowledgement flag and without live containers.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ops.backup_manifest import BackupManifest, REQUIRED_STORES

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run_backup(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.backup.backup_run", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestFixtureBackup(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ops-backup-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = self.tmp / "backup-out"

    def _run_ok(self) -> subprocess.CompletedProcess[str]:
        result = _run_backup("--mode", "fixture", "--out", str(self.out))
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        return result

    def test_fixture_backup_produces_valid_manifest(self) -> None:
        self._run_ok()
        manifest_path = self.out / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        m = BackupManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual({s.name for s in m.stores}, set(REQUIRED_STORES))
        self.assertEqual(m.encryption, "none")
        # Defaults per runbook: RPO 24h, RTO 4h for pilot stage.
        self.assertEqual(m.rpo_target_seconds, 24 * 3600)
        self.assertEqual(m.rto_target_seconds, 4 * 3600)
        self.assertTrue(m.manifest_id.startswith("BKUP-"))

    def test_sha256sums_file_matches_artifacts(self) -> None:
        self._run_ok()
        sums = (self.out / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(sums), len(REQUIRED_STORES))
        for line in sums:
            digest, rel = line.split("  ", 1)
            artifact = (self.out / rel).read_bytes()
            self.assertEqual(hashlib.sha256(artifact).hexdigest(), digest)

    def test_manifest_entries_match_artifacts(self) -> None:
        self._run_ok()
        m = BackupManifest.from_json(
            (self.out / "manifest.json").read_text(encoding="utf-8")
        )
        for store in m.stores:
            data = (self.out / store.artifact_rel_path).read_bytes()
            self.assertTrue(
                m.verify_artifact(store.name, data),
                f"artifact for {store.name} does not match manifest",
            )

    def test_restore_conformance_fixture_bytes_match_source(self) -> None:
        """Every source fixture byte must appear in the packaged stores."""
        self._run_ok()
        for store in sorted(REQUIRED_STORES):
            src_dir = FIXTURES / store
            artifact = self.out / "artifacts" / f"{store}.tar.gz"
            self.assertTrue(artifact.is_file(), f"missing artifact {artifact}")
            import tarfile

            with tarfile.open(artifact, "r:gz") as tf:
                members = {}
                for m in tf.getmembers():
                    if m.isfile():
                        f = tf.extractfile(m)
                        assert f is not None
                        members[m.name] = f.read()
            for path in sorted(src_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(src_dir).as_posix()
                self.assertIn(rel, members, f"{store}: missing {rel} in artifact")
                self.assertEqual(
                    members[rel],
                    path.read_bytes(),
                    f"{store}: byte mismatch for {rel}",
                )

    def test_non_utf8_filename_in_store_is_preserved(self) -> None:
        # Create a fixture file with a non-UTF8 byte in the name inside a
        # copied fixture tree (we never mutate the checked-in fixtures).
        custom = self.tmp / "fixtures-custom"
        shutil.copytree(FIXTURES, custom)
        weird = custom / "erp_private_files" / "private" / "b\xf8razil-note.txt"
        weird.write_bytes(b"synthetic non-utf8-name payload\n")
        result = _run_backup(
            "--mode", "fixture",
            "--fixture-root", str(custom),
            "--out", str(self.out),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        import tarfile

        with tarfile.open(self.out / "artifacts" / "erp_private_files.tar.gz", "r:gz") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
        self.assertIn("private/b\xf8razil-note.txt", names)


class TestFixtureBackupFailures(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ops-backup-fail-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_missing_fixture_store_fails_with_no_partial_manifest(self) -> None:
        broken = self.tmp / "fixtures-broken"
        shutil.copytree(FIXTURES, broken)
        shutil.rmtree(broken / "erp_db")
        out = self.tmp / "out"
        result = _run_backup(
            "--mode", "fixture",
            "--fixture-root", str(broken),
            "--out", str(out),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("erp_db", result.stderr + result.stdout)
        self.assertFalse((out / "manifest.json").exists())

    def test_empty_fixture_store_fails_closed_without_allow_empty(self) -> None:
        """OPS-QA-R1-F-01: an empty store is a backup failure unless the
        store is explicitly allow_empty (fixture mode never marks it)."""
        broken = self.tmp / "fixtures-empty"
        shutil.copytree(FIXTURES, broken)
        for p in (broken / "erp_private_files").rglob("*"):
            if p.is_file():
                p.unlink()
        out = self.tmp / "out-empty"
        result = _run_backup(
            "--mode", "fixture",
            "--fixture-root", str(broken),
            "--out", str(out),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("erp_private_files", result.stderr + result.stdout)
        self.assertFalse((out / "manifest.json").exists())

    def test_out_dir_inside_fixture_root_is_rejected(self) -> None:
        """OPS-QA-R1-F-03: backup must not swallow its own source."""
        out = FIXTURES / "self-including-out"
        result = _run_backup(
            "--mode", "fixture",
            "--fixture-root", str(FIXTURES),
            "--out", str(out),
        )
        self.addCleanup(shutil.rmtree, out, True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture", (result.stderr + result.stdout).lower())
        self.assertFalse((out / "manifest.json").exists())

    def test_out_dir_equal_to_fixture_root_is_rejected(self) -> None:
        result = _run_backup(
            "--mode", "fixture",
            "--fixture-root", str(FIXTURES),
            "--out", str(FIXTURES),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_unwritable_out_dir_fails(self) -> None:
        blocker = self.tmp / "blocker"
        blocker.write_text("i am a file, not a dir")
        out = blocker / "impossible"
        result = _run_backup("--mode", "fixture", "--out", str(out))
        self.assertNotEqual(result.returncode, 0)

    def test_unknown_mode_fails(self) -> None:
        result = _run_backup("--mode", "production", "--out", str(self.tmp / "o"))
        self.assertNotEqual(result.returncode, 0)


class TestPilotModeGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ops-pilot-guard-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_pilot_mode_refuses_without_acknowledgement_flag(self) -> None:
        result = _run_backup("--mode", "pilot", "--out", str(self.tmp / "o"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("--i-understand-local-only", result.stderr + result.stdout)

    def test_pilot_mode_refuses_when_containers_down(self) -> None:
        ps = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=15,
        )
        if ps.returncode == 0 and "erpnext-pilot-db" in ps.stdout.splitlines():
            self.skipTest("pilot db container is up; guard would not trigger")
        result = _run_backup(
            "--mode", "pilot",
            "--i-understand-local-only",
            "--out", str(self.tmp / "o"),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("erpnext-pilot-db", result.stderr + result.stdout)
        self.assertFalse((self.tmp / "o" / "manifest.json").exists())


class TestPilotDbDumpSecretHandling(unittest.TestCase):
    """OPS-QA-R1-F-02: DB root password must never appear in argv/procfs.

    A fake ``docker`` executable records its argv and stdin; the real code
    under test (``_pilot_db_dump``) is then pointed at it via PATH.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ops-pilot-secret-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.probe_argv = self.tmp / "argv.txt"
        self.probe_stdin = self.tmp / "stdin.txt"
        fake_bin = self.tmp / "bin"
        fake_bin.mkdir()
        script = fake_bin / "docker"
        script.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" > {self.probe_argv}\n"
            f"cat > {self.probe_stdin}\n"
            "# emulate a dump on stdout\n"
            "printf -- '-- fake dump\\n'\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        self.env_dir = self.tmp / "env"
        self.env_dir.mkdir()
        (self.env_dir / ".env").write_text(
            "DB_ROOT_PASSWORD=topsecret-probe-value\r\nSITE_NAME=erpnext-pilot.localhost\r\n",
            encoding="utf-8",
        )
        self.fake_bin = fake_bin

    def test_password_not_in_argv_but_reaches_stdin(self) -> None:
        from scripts.backup import backup_run

        old_path = os.environ.get("PATH", "")
        old_env_dir = backup_run.PILOT_ENV_DIR
        os.environ["PATH"] = f"{self.fake_bin}{os.pathsep}{old_path}"
        backup_run.PILOT_ENV_DIR = self.env_dir
        try:
            dest = self.tmp / "dump.sql"
            backup_run._pilot_db_dump(dest)
        finally:
            os.environ["PATH"] = old_path
            backup_run.PILOT_ENV_DIR = old_env_dir

        secret = "topsecret-probe-value"
        argv_text = self.probe_argv.read_text(encoding="utf-8")
        self.assertNotIn(secret, argv_text,
                         f"password leaked into argv: {argv_text!r}")
        # No -e VAR=secret style env injection on argv either.
        self.assertNotIn("MARIADB_PWD=", argv_text)
        stdin_text = self.probe_stdin.read_text(encoding="utf-8")
        self.assertIn(secret, stdin_text,
                      "password must reach the container shell via stdin script")
        self.assertEqual(dest.read_text(encoding="utf-8"), "-- fake dump\n")

    def test_crlf_env_password_is_stripped(self) -> None:
        from scripts.backup import backup_run

        old_path = os.environ.get("PATH", "")
        old_env_dir = backup_run.PILOT_ENV_DIR
        os.environ["PATH"] = f"{self.fake_bin}{os.pathsep}{old_path}"
        backup_run.PILOT_ENV_DIR = self.env_dir
        try:
            backup_run._pilot_db_dump(self.tmp / "d.sql")
        finally:
            os.environ["PATH"] = old_path
            backup_run.PILOT_ENV_DIR = old_env_dir
        stdin_text = self.probe_stdin.read_text(encoding="utf-8")
        self.assertNotIn("\r", stdin_text)


class TestPilotRealCapture(unittest.TestCase):
    """OPS-QA-R1-F-06: pilot app_config/audit_state capture real data."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ops-pilot-capture-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # _pilot_capture_audit_state requires DB_ROOT_PASSWORD from the pilot
        # .env; PILOT_ENV_DIR is redirected to this isolated tmp dir.
        (self.tmp / ".env").write_text(
            "DB_ROOT_PASSWORD=fake-capture-pw\nSITE_NAME=erpnext-pilot.localhost\n",
            encoding="utf-8",
        )
        fake_bin = self.tmp / "bin"
        fake_bin.mkdir()
        self.calls = self.tmp / "docker-calls.txt"
        # Fake docker: handles `exec <container> sh -c 'cat ...'` by emitting
        # canned files; handles `exec -i <db> sh -s` by emitting counts when
        # the stdin script contains COUNT queries.
        script = fake_bin / "docker"
        script.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" >> {self.calls}\n"
            "last=\"\"\n"
            "for _a in \"$@\"; do last=\"$_a\"; done\n"
            "case \"$last\" in\n"
            "  *site_config.json*)\n"
            "    if printf '%s' \"$last\" | grep -q 'common_site_config'; then\n"
            "      printf '%s' '{\"redis_cache\":\"redis://x\",\"admin_password\":\"LIVE-ADMIN-9\"}'\n"
            "    else\n"
            "      printf '%s' '{\"db_name\":\"erp\",\"db_password\":\"LIVE-DB-PW-9\",\"encryption_key\":\"LIVE-ENC-9\",\"mail_password\":\"LIVE-MAIL-9\",\"config_version\":\"pilotcfg-1\",\"app_version\":\"15\"}'\n"
            "    fi\n"
            "    ;;\n"
            "  *apps.json*)\n"
            "    printf '%s' '[\"frappe\",\"erpnext\"]'\n"
            "    ;;\n"
            "  *)\n"
            "    if [ \"$1\" = \"exec\" ] && [ \"$2\" = \"-i\" ]; then\n"
            "      # stdin script mode: emit one count per line for each SELECT COUNT\n"
            "      counts=$(grep -c 'SELECT COUNT' /dev/stdin || true)\n"
            "      i=0; while [ $i -lt $counts ]; do echo 42; i=$((i+1)); done\n"
            "    fi\n"
            "    ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        self.fake_bin = fake_bin

    def _patched(self):
        import contextlib
        from scripts.backup import backup_run

        @contextlib.contextmanager
        def ctx():
            old_path = os.environ.get("PATH", "")
            old_env = backup_run.PILOT_ENV_DIR
            os.environ["PATH"] = f"{self.fake_bin}{os.pathsep}{old_path}"
            backup_run.PILOT_ENV_DIR = self.tmp  # unused here but isolated
            try:
                yield backup_run
            finally:
                os.environ["PATH"] = old_path
                backup_run.PILOT_ENV_DIR = old_env

        return ctx()

    def test_pilot_app_config_is_real_and_redacted(self) -> None:
        with self._patched() as backup_run:
            dest = self.tmp / "cfg"
            dest.mkdir()
            backup_run._pilot_capture_app_config(dest)
            site_config = json.loads((dest / "site_config.json").read_text())
            self.assertEqual(site_config["db_password"], "[REDACTED]")
            self.assertEqual(site_config["encryption_key"], "[REDACTED]")
            self.assertEqual(site_config["mail_password"], "[REDACTED]")
            self.assertEqual(site_config["config_version"], "pilotcfg-1")
            common = json.loads((dest / "common_site_config.json").read_text())
            self.assertEqual(common["admin_password"], "[REDACTED]")
            self.assertTrue((dest / "apps.json").is_file())
            # config_version.txt sidecar derived from the real config
            self.assertEqual(
                (dest / "config_version.txt").read_text().strip(), "pilotcfg-1"
            )
            # Leak probe over the whole directory.
            blob = b""
            for p in sorted(dest.rglob("*")):
                if p.is_file():
                    blob += p.read_bytes()
            for secret in (b"LIVE-DB-PW-9", b"LIVE-ENC-9", b"LIVE-MAIL-9",
                           b"LIVE-ADMIN-9"):
                self.assertNotIn(secret, blob)

    def test_pilot_audit_state_counts_and_surrogate_head(self) -> None:
        import hashlib
        with self._patched() as backup_run:
            dest = self.tmp / "audit"
            dest.mkdir()
            backup_run._pilot_capture_audit_state(dest)
            counts = json.loads((dest / "record_counts.json").read_text())
            self.assertEqual(counts["source"], "pilot")
            self.assertEqual(counts["tables"]["tabSales Invoice"], 42)
            self.assertEqual(counts["tables"]["tabPayment Entry"], 42)
            self.assertEqual(counts["tables"]["tabGL Entry"], 42)
            head = (dest / "audit_head.txt").read_text().strip()
            self.assertRegex(head, r"^sha256:[0-9a-f]{64}$")
            expected = hashlib.sha256(
                (dest / "record_counts.json").read_bytes()
            ).hexdigest()
            self.assertEqual(head, f"sha256:{expected}")

    def test_pilot_audit_state_tolerates_missing_table(self) -> None:
        # Fake docker returns empty output (rc 0) -> counts None, file exists.
        script = self.fake_bin / "docker"
        script.write_text(
            "#!/bin/sh\nexit 0\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        with self._patched() as backup_run:
            dest = self.tmp / "audit2"
            dest.mkdir()
            backup_run._pilot_capture_audit_state(dest)
            counts = json.loads((dest / "record_counts.json").read_text())
            self.assertIsNone(counts["tables"]["tabSales Invoice"])
            self.assertTrue((dest / "audit_head.txt").is_file())


if __name__ == "__main__":
    unittest.main()
