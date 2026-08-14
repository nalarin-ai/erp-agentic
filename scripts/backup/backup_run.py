"""Multi-store backup runner (OPS-001, slice 2).

Usage:
    python3 -m scripts.backup.backup_run --mode fixture --out DIR
    python3 -m scripts.backup.backup_run --mode pilot --i-understand-local-only --out DIR

Fixture mode packages the synthetic stores under ``tests/operations/fixtures``
(or ``--fixture-root``) and never touches the pilot environment.

Pilot mode dumps the ERP database via ``docker exec`` (credentials are passed
inside the container environment, never on the host command line), archives
the ``sites`` volume's private files, snapshots app configuration and the
integration audit state, and writes a manifest. It REFUSES to run (exit 2)
unless the pilot containers are up AND the operator passes
``--i-understand-local-only``.

Encryption at rest is out of scope at this stage; the manifest records
``encryption: none`` and the operations runbook tracks the production
requirement (R-009).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.backup_manifest import (  # noqa: E402
    BackupManifest,
    REQUIRED_STORES,
    StoreEntry,
)

DEFAULT_FIXTURE_ROOT = REPO_ROOT / "tests" / "operations" / "fixtures"
PILOT_ENV_DIR = REPO_ROOT / "environments" / "erpnext-pilot"
PILOT_DB_CONTAINER = "erpnext-pilot-db"
PILOT_BACKEND_CONTAINER = "erpnext-pilot-backend"
SITES_VOLUME = "erpnext-pilot_sites"

DEFAULT_RPO_SECONDS = 24 * 3600
DEFAULT_RTO_SECONDS = 4 * 3600

EXIT_GUARD_REFUSED = 2
EXIT_FAILED = 1


class BackupError(RuntimeError):
    """Fatal backup failure; no partial manifest is written."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pack_dir_tar(src_dir: Path, artifact_path: Path, *, allow_empty: bool = False) -> int:
    """Package a store directory into a gzipped tar of relative file paths.

    Returns the number of files packed. Fail-closed on an empty source
    unless ``allow_empty`` is passed — an empty store must be an explicit,
    manifest-recorded contract (OPS-QA-R1-F-01).
    """
    if not src_dir.is_dir():
        raise BackupError(f"store source missing: {src_dir}")
    files = [p for p in sorted(src_dir.rglob("*")) if p.is_file()]
    if not files and not allow_empty:
        raise BackupError(f"store source empty: {src_dir}")
    with tarfile.open(artifact_path, "w:gz") as tf:
        for path in files:
            rel = path.relative_to(src_dir).as_posix()
            tf.add(path, arcname=rel)
    return len(files)


def _write_manifest_and_sums(
    out_dir: Path,
    artifacts: dict[str, Path],
    rpo: int,
    rto: int,
    *,
    empty_stores: frozenset[str] = frozenset(),
    allow_empty_stores: frozenset[str] = frozenset(),
    store_sources: dict[str, str] | None = None,
) -> BackupManifest:
    store_sources = store_sources or {}
    stores = tuple(
        StoreEntry(
            name=name,
            artifact_rel_path=f"artifacts/{name}.tar.gz",
            sha256=_sha256_file(artifacts[name]),
            byte_size=artifacts[name].stat().st_size,
            allow_empty=name in allow_empty_stores,
            empty=name in empty_stores,
            source=store_sources.get(name),
        )
        for name in sorted(artifacts)
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest = BackupManifest(
        manifest_id=f"BKUP-{stamp}-{uuid.uuid4().hex[:8]}",
        created_at=datetime.now(timezone.utc),
        stores=stores,
        rpo_target_seconds=rpo,
        rto_target_seconds=rto,
    )
    (out_dir / "manifest.json").write_text(manifest.canonical_json(), encoding="utf-8")
    sums = "".join(
        f"{s.sha256}  {s.artifact_rel_path}\n" for s in manifest.stores
    )
    (out_dir / "SHA256SUMS").write_text(sums, encoding="utf-8")
    return manifest


def _prepare_out(out_dir: Path) -> Path:
    try:
        (out_dir / "artifacts").mkdir(parents=True, exist_ok=False)
    except (OSError, FileExistsError) as exc:
        raise BackupError(f"cannot create output dir {out_dir}: {exc}") from exc
    return out_dir / "artifacts"


def run_fixture(fixture_root: Path, out_dir: Path, rpo: int, rto: int) -> BackupManifest:
    fixture_resolved = fixture_root.resolve()
    out_resolved = out_dir.resolve()
    if out_resolved == fixture_resolved or fixture_resolved in out_resolved.parents:
        raise BackupError(
            f"output dir {out_dir} is inside the fixture root {fixture_root}; "
            "refusing self-including backup"
        )
    artifacts_dir = _prepare_out(out_dir)
    artifacts: dict[str, Path] = {}
    try:
        for store in sorted(REQUIRED_STORES):
            src = fixture_root / store
            artifact = artifacts_dir / f"{store}.tar.gz"
            _pack_dir_tar(src, artifact)
            artifacts[store] = artifact
        return _write_manifest_and_sums(
            out_dir, artifacts, rpo, rto,
            store_sources={name: "fixture" for name in artifacts},
        )
    except Exception:
        # Fail-closed: remove partial output so no half-manifest survives.
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# Pilot mode
# ---------------------------------------------------------------------------


def _pilot_containers_up() -> list[str]:
    """Names of required pilot containers that are NOT running."""
    try:
        ps = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [PILOT_DB_CONTAINER, PILOT_BACKEND_CONTAINER]
    running = set(ps.stdout.splitlines()) if ps.returncode == 0 else set()
    required = {PILOT_DB_CONTAINER, PILOT_BACKEND_CONTAINER}
    return sorted(required - running)


def _pilot_db_dump(dest: Path) -> None:
    """mariadb-dump inside the db container; password via stdin only.

    OPS-QA-R1-F-02: the root password is read from the pilot's local .env
    (never committed) and embedded in a small shell script piped to
    ``docker exec -i <db> sh -s`` via stdin. It never appears in any host
    argv element (``ps``/procfs safe) and is never printed.
    """
    env_file = PILOT_ENV_DIR / ".env"
    if not env_file.is_file():
        raise BackupError(f"pilot .env not found at {env_file}; run generate-secrets.sh")
    password = ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DB_ROOT_PASSWORD="):
            # .strip() also tolerates CRLF line endings in the .env file.
            password = line.split("=", 1)[1].strip()
    if not password:
        raise BackupError("DB_ROOT_PASSWORD missing in pilot .env")
    if "\n" in password or "\r" in password:
        raise BackupError("DB_ROOT_PASSWORD contains a newline; refusing")
    if "'" in password:
        raise BackupError(
            "DB_ROOT_PASSWORD contains a single quote; rotate it "
            "(generate-secrets.sh produces quote-free secrets)"
        )
    script = (
        "set -eu\n"
        f"export MARIADB_PWD='{password}'\n"
        'mariadb-dump -u root -p"$MARIADB_PWD" --all-databases --single-transaction\n'
    )
    result = subprocess.run(
        ["docker", "exec", "-i", PILOT_DB_CONTAINER, "sh", "-s"],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=300,
    )
    if result.returncode != 0 or not result.stdout:
        raise BackupError("mariadb-dump failed inside pilot db container")
    dest.write_bytes(result.stdout)


def _pilot_volume_tar(volume: str, subpath: str, dest: Path) -> None:
    """Tar a path inside a named volume via a throwaway helper container."""
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{volume}:/vol:ro",
        "-v", f"{dest.parent}:/out",
        "alpine:3",
        "tar", "-czf", f"/out/{dest.name}", "-C", f"/vol/{subpath}", ".",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise BackupError(f"failed to archive volume {volume}:{subpath}: {result.stderr.strip()}")


# Secret-valued keys scrubbed from captured pilot config before anything is
# written to the backup artifact (OPS-QA-R1-F-06). Artifacts must never
# contain live secrets.
_PILOT_CONFIG_SECRET_KEYS: frozenset[str] = frozenset({
    "db_password", "encryption_key", "mail_password", "admin_password",
    "password", "secret", "api_key", "api_secret", "access_token",
})
REDACTED_VALUE = "[REDACTED]"
_PILOT_SITE = "erpnext-pilot.localhost"
_PILOT_AUDIT_TABLES: tuple[str, ...] = (
    "tabSales Invoice", "tabPayment Entry", "tabGL Entry",
)


def _redact_config(obj: object) -> object:
    """Recursively replace secret-valued config keys with REDACTED_VALUE."""
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for k, v in obj.items():
            lowered = str(k).lower()
            if any(s in lowered for s in _PILOT_CONFIG_SECRET_KEYS):
                out[str(k)] = REDACTED_VALUE
            else:
                out[str(k)] = _redact_config(v)
        return out
    if isinstance(obj, list):
        return [_redact_config(v) for v in obj]
    return obj


def _pilot_cat(remote_path: str) -> bytes | None:
    """cat a file inside the backend container; None when absent."""
    result = subprocess.run(
        ["docker", "exec", PILOT_BACKEND_CONTAINER, "sh", "-c",
         f"cat {remote_path}"],
        capture_output=True, timeout=60,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _pilot_capture_app_config(dest: Path) -> None:
    """Capture REAL pilot app config into ``dest`` with secrets redacted.

    Writes site_config.json, common_site_config.json, apps.json, and a
    config_version.txt sidecar derived from the live site config.
    """
    site_dir = f"sites/{_PILOT_SITE}"
    raw_site = _pilot_cat(f"{site_dir}/site_config.json")
    if raw_site is None:
        raise BackupError(
            f"pilot site_config.json not readable at {site_dir} "
            f"in {PILOT_BACKEND_CONTAINER}"
        )
    try:
        site_cfg = json.loads(raw_site.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError(f"pilot site_config.json invalid JSON: {exc}") from exc
    if not isinstance(site_cfg, dict):
        raise BackupError("pilot site_config.json is not a JSON object")
    redacted_site = _redact_config(site_cfg)
    (dest / "site_config.json").write_text(
        json.dumps(redacted_site, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    version = site_cfg.get("config_version")
    if version is None:
        # Live ERPNext site configs do not carry a config_version key; the
        # sidecar marker stays truthful, and the redacted artifact itself is
        # the config evidence.
        version = redacted_site.get("config_version")
    (dest / "config_version.txt").write_text(
        (str(version) if version is not None else "pilot-captured") + "\n",
        encoding="utf-8",
    )
    for name, remote in (
        ("apps.json", "sites/apps.json"),
        ("common_site_config.json", "sites/common_site_config.json"),
    ):
        raw = _pilot_cat(remote)
        if raw is None:
            continue  # optional file; pilot flexibility
        try:
            parsed = json.loads(raw.decode("utf-8"))
            (dest / name).write_text(
                json.dumps(_redact_config(parsed), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Non-JSON (apps.txt-style): never copy raw, keep a stub marker.
            (dest / name).write_text("{}\n", encoding="utf-8")


def _pilot_capture_audit_state(dest: Path) -> None:
    """Capture REAL pilot audit state: per-table row counts + surrogate head.

    Runs COUNT(*) queries only (no row data leaves the database). Missing
    tables record null and processing continues (pilot flexibility). The
    audit_head.txt surrogate is the sha256 of the canonical record_counts
    content — documented as a pilot-stage surrogate for the audit chain
    head (OPS-QA-R1-F-06).
    """
    password = ""
    env_file = PILOT_ENV_DIR / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DB_ROOT_PASSWORD="):
                password = line.split("=", 1)[1].strip()
    if not password:
        raise BackupError("DB_ROOT_PASSWORD missing in pilot .env")
    selects = "\n".join(
        f"SELECT COUNT(*) FROM `{t}`;" for t in _PILOT_AUDIT_TABLES
    )
    script = (
        "set -u\n"
        f"export MARIADB_PWD='{password}'\n"
        'mariadb -u root -p"$MARIADB_PWD" -N -e "\n'
        f"{selects}\"\n"
    )
    result = subprocess.run(
        ["docker", "exec", "-i", PILOT_DB_CONTAINER, "sh", "-s"],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=120,
    )
    lines = (
        result.stdout.decode("utf-8", errors="replace").splitlines()
        if result.returncode == 0 else []
    )
    tables: dict[str, int | None] = {}
    for idx, table in enumerate(_PILOT_AUDIT_TABLES):
        count: int | None = None
        if idx < len(lines):
            try:
                count = int(lines[idx].strip())
            except ValueError:
                count = None
        tables[table] = count
    counts = {
        "source": "pilot",
        "note": ("pilot-stage surrogate: per-table COUNT(*) of core ERP "
                 "tables; audit_head.txt is sha256 of this file's canonical "
                 "content"),
        "tables": tables,
    }
    (dest / "record_counts.json").write_text(
        json.dumps(counts, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # audit_head.txt pins the exact bytes of record_counts.json so restore
    # reconciliation compares byte-for-byte (sha256 of the file as written).
    head = hashlib.sha256((dest / "record_counts.json").read_bytes()).hexdigest()
    (dest / "audit_head.txt").write_text(f"sha256:{head}\n", encoding="utf-8")


def run_pilot(out_dir: Path, rpo: int, rto: int) -> BackupManifest:
    missing = _pilot_containers_up()
    if missing:
        raise BackupError(
            "pilot containers not running: " + ", ".join(missing) +
            " (start with environments/erpnext-pilot/start.sh)"
        )
    artifacts_dir = _prepare_out(out_dir)
    try:
        with tempfile.TemporaryDirectory(prefix="ops-pilot-") as tmp_s:
            tmp = Path(tmp_s)
            db_sql = tmp / "erp_db.sql"
            _pilot_db_dump(db_sql)
            db_tar = artifacts_dir / "erp_db.tar.gz"
            with tarfile.open(db_tar, "w:gz") as tf:
                tf.add(db_sql, arcname="dump.sql")

            _pilot_volume_tar(SITES_VOLUME, "", tmp / "sites.tar.gz")

            artifacts: dict[str, Path] = {"erp_db": db_tar}
            empty_stores: set[str] = set()
            # Private files: repackage only the private subtree per site.
            # Legitimately empty pre-production (OPS-QA-R1-F-01): recorded
            # explicitly via the manifest allow_empty/empty contract.
            files_tar = artifacts_dir / "erp_private_files.tar.gz"
            packed_files = 0
            with tarfile.open(tmp / "sites.tar.gz", "r:gz") as src_tf, \
                    tarfile.open(files_tar, "w:gz") as dst_tf:
                for member in src_tf.getmembers():
                    if member.isfile() and "/private/" in member.name:
                        f = src_tf.extractfile(member)
                        if f is None:
                            continue
                        data = f.read()
                        info = tarfile.TarInfo(member.name)
                        info.size = len(data)
                        dst_tf.addfile(info, __import__("io").BytesIO(data))
                        packed_files += 1
            if packed_files == 0:
                empty_stores.add("erp_private_files")
            artifacts["erp_private_files"] = files_tar

            # App config + audit state: REAL pilot captures with secret
            # redaction and COUNT-only queries (OPS-QA-R1-F-06) — never
            # fixture copies.
            cfg_dir = tmp / "app_config"
            cfg_dir.mkdir()
            _pilot_capture_app_config(cfg_dir)
            cfg_tar = artifacts_dir / "app_config.tar.gz"
            _pack_dir_tar(cfg_dir, cfg_tar)
            artifacts["app_config"] = cfg_tar

            audit_dir = tmp / "audit_state"
            audit_dir.mkdir()
            _pilot_capture_audit_state(audit_dir)
            audit_tar = artifacts_dir / "audit_state.tar.gz"
            _pack_dir_tar(audit_dir, audit_tar)
            artifacts["audit_state"] = audit_tar

        return _write_manifest_and_sums(
            out_dir, artifacts, rpo, rto,
            empty_stores=frozenset(empty_stores),
            allow_empty_stores=frozenset({"erp_private_files"}),
            store_sources={name: "pilot" for name in artifacts},
        )
    except Exception:
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OPS-001 multi-store backup runner")
    parser.add_argument("--mode", choices=["fixture", "pilot"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    parser.add_argument("--i-understand-local-only", action="store_true",
                        help="required acknowledgement for pilot mode")
    parser.add_argument("--rpo-seconds", type=int, default=DEFAULT_RPO_SECONDS)
    parser.add_argument("--rto-seconds", type=int, default=DEFAULT_RTO_SECONDS)
    args = parser.parse_args(argv)

    if args.mode == "pilot" and not args.i_understand_local_only:
        print(
            "REFUSED: pilot mode requires --i-understand-local-only. "
            "Pilot backups touch the local isolated environment only; "
            "this acknowledgement prevents accidental runs against it.",
            file=sys.stderr,
        )
        return EXIT_GUARD_REFUSED

    try:
        if args.mode == "fixture":
            manifest = run_fixture(args.fixture_root, args.out,
                                   args.rpo_seconds, args.rto_seconds)
        else:
            manifest = run_pilot(args.out, args.rpo_seconds, args.rto_seconds)
    except BackupError as exc:
        print(f"BACKUP_FAILED: {exc}", file=sys.stderr)
        return EXIT_GUARD_REFUSED if "pilot containers" in str(exc) else EXIT_FAILED
    except OSError as exc:
        print(f"BACKUP_FAILED: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(f"BACKUP_OK manifest={manifest.manifest_id} stores={len(manifest.stores)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
