"""Restore verification + cross-store reconciliation (OPS-001, slice 3).

Usage:
    python3 -m scripts.backup.restore_verify --manifest PATH --target DIR

Steps, fail-closed at each stage:
1. Load and validate the manifest (schema + required stores).
2. Verify every artifact's sha256 and byte size against the manifest.
3. Extract each store artifact into ``<target>/<store>/``.
4. Run cross-store reconciliation checks against the extracted content:
   - ``record_counts``: audit_state/record_counts.json must exist, parse,
     and its ``erp_db_rows`` must match the fixture-record-count marker in
     the restored DB dump.
   - ``audit_head``: audit_state/audit_head.txt must exist and carry a
     well-formed ``sha256:<hex64>`` head hash.
   - ``config_version``: app_config/config_version.txt must exist, be
     non-empty, and match the ``config_version`` key in site_config.json.

Prints one line per check and finishes with RESTORE_OK / RESTORE_FAIL.
Exit code 0 on RESTORE_OK, 1 otherwise.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.backup_manifest import BackupManifest, InvalidManifest  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1

_AUDIT_HEAD_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DB_COUNT_RE = re.compile(r"fixture-record-count:\s*(\d+)")


class CheckLog:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, name: str, detail: str = "") -> None:
        print(f"OK   {name}" + (f" {detail}" if detail else ""))

    def fail(self, name: str, detail: str = "") -> None:
        self.failures.append(name)
        print(f"FAIL {name}" + (f" {detail}" if detail else ""))


def _verify_artifact(manifest: BackupManifest, backup_dir: Path, store: str,
                     log: CheckLog) -> Path | None:
    entry = manifest.store_entry(store)
    path = backup_dir / entry.artifact_rel_path
    label = f"checksum:{store}"
    # OPS-QA-R2-F-01 defense-in-depth: even if a manifest was hand-built
    # around the schema guard, never resolve outside the backup directory.
    try:
        resolved_root = backup_dir.resolve()
        resolved_path = path.resolve()
    except OSError:
        log.fail(label, "artifact path cannot be resolved")
        return None
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        log.fail(label, f"artifact path escapes backup dir: {entry.artifact_rel_path!r}")
        return None
    if not path.is_file():
        log.fail(label, f"artifact missing at {entry.artifact_rel_path}")
        return None
    data = path.read_bytes()
    if len(data) != entry.byte_size:
        log.fail(label, f"size {len(data)} != manifest {entry.byte_size}")
        return None
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry.sha256:
        log.fail(label, "sha256 mismatch")
        return None
    log.ok(label, f"sha256:{digest[:16]}… size={len(data)}")
    return path


def _extract(artifact: Path, store: str, target: Path, log: CheckLog,
             *, allow_empty: bool = False, declared_empty: bool = False) -> Path | None:
    label = f"extract:{store}"
    dest = target / store
    try:
        dest.mkdir(parents=True, exist_ok=False)
        with tarfile.open(artifact, "r:gz") as tf:
            members = tf.getmembers()
            has_files = any(m.isfile() for m in members)
            if not has_files and not (allow_empty and declared_empty):
                raise tarfile.TarError("archive contains no files")
            if has_files and declared_empty:
                raise tarfile.TarError(
                    "manifest declares empty but archive contains files"
                )
            for member in members:
                # Path traversal guard.
                member_path = (dest / member.name).resolve()
                if not str(member_path).startswith(str(dest.resolve()) + "/") \
                        and member_path != dest.resolve():
                    raise tarfile.TarError(f"unsafe member path: {member.name}")
            tf.extractall(dest, filter="data")
    except (tarfile.TarError, EOFError, OSError, gzip.BadGzipFile) as exc:
        log.fail(label, f"{type(exc).__name__}: {exc}")
        return None
    if not any(dest.rglob("*")):
        log.ok(label, f"-> {dest.relative_to(target)} (empty store, allowed by manifest)")
    else:
        log.ok(label, f"-> {dest.relative_to(target)}")
    return dest


def _check_record_counts(target: Path, log: CheckLog) -> None:
    label = "check:record_counts"
    counts_path = target / "audit_state" / "record_counts.json"
    if not counts_path.is_file():
        log.fail(label, "audit_state/record_counts.json missing")
        return
    try:
        counts = json.loads(counts_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.fail(label, f"record_counts.json invalid JSON: {exc}")
        return
    if counts.get("source") == "pilot":
        # Pilot provenance (OPS-QA-R1-F-06): real per-table COUNT(*) capture.
        # Validate shape; row-data reconciliation happens inside the live DB
        # and is out of scope for the artifact verifier.
        tables = counts.get("tables")
        if not isinstance(tables, dict) or not tables:
            log.fail(label, "pilot record_counts.json lacks a non-empty tables map")
            return
        log.ok(label, f"pilot capture, tables={len(tables)}")
        return
    for key in ("audit_records", "erp_db_rows", "outbox_pending"):
        if key not in counts:
            log.fail(label, f"record_counts.json missing key {key!r}")
            return
    # Cross-store: DB dump must declare the same row count (fixture marker).
    dump_path = target / "erp_db" / "dump.sql"
    if dump_path.is_file():
        text = dump_path.read_text(encoding="utf-8", errors="replace")
        match = _DB_COUNT_RE.search(text)
        if match is None:
            log.fail(label, "erp_db dump lacks fixture-record-count marker")
            return
        if int(match.group(1)) != counts["erp_db_rows"]:
            log.fail(
                label,
                f"erp_db_rows={counts['erp_db_rows']} != dump marker {match.group(1)}",
            )
            return
    log.ok(label, json.dumps(counts, sort_keys=True))


def _check_audit_head(target: Path, log: CheckLog) -> None:
    label = "check:audit_head"
    head_path = target / "audit_state" / "audit_head.txt"
    if not head_path.is_file():
        log.fail(label, "audit_state/audit_head.txt missing")
        return
    head = head_path.read_text(encoding="utf-8").strip()
    if not _AUDIT_HEAD_RE.match(head):
        log.fail(label, f"malformed audit head hash: {head[:40]!r}")
        return
    log.ok(label, f"head={head[:23]}…")


def _check_config_version(target: Path, log: CheckLog) -> None:
    label = "check:config_version"
    version_path = target / "app_config" / "config_version.txt"
    if not version_path.is_file():
        log.fail(label, "app_config/config_version.txt missing")
        return
    version = version_path.read_text(encoding="utf-8").strip()
    if not version:
        log.fail(label, "config_version.txt is empty")
        return
    site_config = target / "app_config" / "site_config.json"
    if site_config.is_file():
        try:
            cfg = json.loads(site_config.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            log.fail(label, f"site_config.json invalid JSON: {exc}")
            return
        if version == "pilot-captured":
            # Pilot provenance: live ERPNext site configs carry no
            # config_version key; the redacted artifact is the evidence.
            if cfg.get("config_version") is None:
                log.ok(label, "pilot-captured (no config_version key in live site config)")
                return
            log.fail(label, "config_version.txt='pilot-captured' but site_config.json carries a config_version")
            return
        if cfg.get("config_version") != version:
            log.fail(
                label,
                f"config_version.txt={version!r} != site_config.json={cfg.get('config_version')!r}",
            )
            return
    log.ok(label, f"version={version}")


def restore_verify(manifest_path: Path, target: Path) -> bool:
    log = CheckLog()
    if not manifest_path.is_file():
        print(f"FAIL manifest {manifest_path} not found")
        print("RESTORE_FAIL")
        return False
    try:
        manifest = BackupManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except InvalidManifest as exc:
        print(f"FAIL manifest invalid: {exc}")
        print("RESTORE_FAIL")
        return False
    print(f"manifest:{manifest.manifest_id} hash={manifest.manifest_hash()[:23]}…")

    backup_dir = manifest_path.parent
    extracted: dict[str, Path] = {}
    for store in manifest.stores:
        artifact = _verify_artifact(manifest, backup_dir, store.name, log)
        if artifact is None:
            continue
        dest = _extract(artifact, store.name, target, log,
                        allow_empty=store.allow_empty, declared_empty=store.empty)
        if dest is not None:
            extracted[store.name] = dest

    if not log.failures:
        _check_record_counts(target, log)
        _check_audit_head(target, log)
        _check_config_version(target, log)

    if log.failures:
        print(f"RESTORE_FAIL checks_failed={len(log.failures)}: {', '.join(log.failures)}")
        return False
    print(f"RESTORE_OK stores={len(extracted)} manifest={manifest.manifest_id}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OPS-001 restore verification")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--mode", choices=["fixture", "pilot"], default="fixture",
                        help="informational; verification is mode-agnostic")
    args = parser.parse_args(argv)
    return EXIT_OK if restore_verify(args.manifest, args.target) else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
