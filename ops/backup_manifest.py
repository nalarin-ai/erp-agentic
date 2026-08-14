"""Backup manifest for multi-store application-consistent backups (OPS-001).

Pure, deterministic, stdlib-only. Implements ARCHITECTURE.md §9: the manifest
covers the ERP database, private files, configuration, custom app state, and
integration audit state. Validation is fail-closed: a manifest missing a
required store, or with negative RPO/RTO targets, is invalid.

The canonical JSON serialization (sorted keys, no incidental whitespace) and
the manifest hash deliberately exclude ``manifest_id`` and ``created_at`` so
the hash binds *content* (store digests + recovery targets), not the moment
the backup was taken. That lets two backups of identical content compare
equal and lets restore tooling detect content tampering.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

REQUIRED_STORES: frozenset[str] = frozenset(
    {"erp_db", "erp_private_files", "app_config", "audit_state"}
)

_SHA256_HEX_LEN = 64


class InvalidManifest(ValueError):
    """Raised when a manifest or store entry violates the schema."""


@dataclass(frozen=True, slots=True)
class StoreEntry:
    """One logical store covered by the backup.

    ``allow_empty`` records that the store is *legitimately* empty for this
    backup (e.g. a pre-production pilot's private-files volume); restore
    verification then accepts an empty archive for this store only.
    ``empty`` records that the packed artifact in fact contains no files
    (fail-closed: ``empty=True`` requires ``allow_empty=True``).
    ``source`` records provenance: ``"fixture"`` or ``"pilot"`` (None for
    older manifests / hand-built entries).
    """

    name: str
    artifact_rel_path: str
    sha256: str
    byte_size: int
    allow_empty: bool = False
    empty: bool = False
    source: str | None = None

    _ALLOWED_SOURCES: ClassVar[frozenset[str]] = frozenset({"fixture", "pilot"})

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidManifest("store name is required")
        if not self.artifact_rel_path:
            raise InvalidManifest(f"artifact_rel_path required for store {self.name!r}")
        # OPS-QA-R2-F-01: the manifest schema must itself reject absolute
        # paths and parent traversal so a hostile manifest cannot steer the
        # verifier into reading files outside the backup directory.
        _parts = self.artifact_rel_path.replace("\\", "/").split("/")
        if (
            self.artifact_rel_path.startswith("/")
            or self.artifact_rel_path.startswith("~")
            or (len(self.artifact_rel_path) > 1 and self.artifact_rel_path[1] == ":")
            or any(part in ("", ".", "..") for part in _parts)
        ):
            raise InvalidManifest(
                f"artifact_rel_path for store {self.name!r} must be a safe "
                "relative path (no absolute path, no '.'/'..' segments)"
            )
        if (
            len(self.sha256) != _SHA256_HEX_LEN
            or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise InvalidManifest(
                f"sha256 for store {self.name!r} must be 64 lowercase hex chars"
            )
        if self.byte_size < 0:
            raise InvalidManifest(f"byte_size for store {self.name!r} must be >= 0")
        if self.empty and not self.allow_empty:
            raise InvalidManifest(
                f"store {self.name!r} packed empty but is not marked allow_empty; "
                "fail-closed: an empty store must be an explicit contract"
            )
        if self.source is not None and self.source not in self._ALLOWED_SOURCES:
            raise InvalidManifest(
                f"source for store {self.name!r} must be one of "
                f"{sorted(self._ALLOWED_SOURCES)} or None"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "allow_empty": self.allow_empty,
            "artifact_rel_path": self.artifact_rel_path,
            "byte_size": self.byte_size,
            "empty": self.empty,
            "name": self.name,
            "sha256": self.sha256,
            "source": self.source,
        }

    _KNOWN_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"name", "artifact_rel_path", "sha256", "byte_size",
         "allow_empty", "empty", "source"}
    )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> StoreEntry:
        if not isinstance(data, dict):
            raise InvalidManifest("store entry must be a JSON object")
        unknown = set(data) - cls._KNOWN_FIELDS
        if unknown:
            raise InvalidManifest(
                f"store entry has unknown fields: {sorted(unknown)}"
            )
        source_raw = data.get("source")
        try:
            byte_size = int(data["byte_size"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidManifest(
                f"store entry byte_size invalid: {exc}"
            ) from exc
        try:
            return cls(
                name=str(data["name"]),
                artifact_rel_path=str(data["artifact_rel_path"]),
                sha256=str(data["sha256"]),
                byte_size=byte_size,
                allow_empty=bool(data.get("allow_empty", False)),
                empty=bool(data.get("empty", False)),
                source=None if source_raw is None else str(source_raw),
            )
        except KeyError as exc:
            raise InvalidManifest(f"store entry missing field: {exc}") from exc


@dataclass(frozen=True, slots=True)
class BackupManifest:
    """Application-consistent multi-store backup manifest."""

    manifest_id: str
    created_at: datetime
    stores: tuple[StoreEntry, ...]
    rpo_target_seconds: int
    rto_target_seconds: int
    encryption: str = "none"

    def __post_init__(self) -> None:
        if not self.manifest_id:
            raise InvalidManifest("manifest_id is required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidManifest("created_at must be timezone-aware")
        if self.rpo_target_seconds < 0:
            raise InvalidManifest("rpo_target_seconds must be >= 0")
        if self.rto_target_seconds < 0:
            raise InvalidManifest("rto_target_seconds must be >= 0")
        if self.encryption != "none":
            raise InvalidManifest(
                f"unsupported encryption mode {self.encryption!r}; "
                "only 'none' is implemented in this stage (see runbook)"
            )
        names = [s.name for s in self.stores]
        if len(set(names)) != len(names):
            raise InvalidManifest("duplicate store entries")
        missing = REQUIRED_STORES - set(names)
        if missing:
            raise InvalidManifest(f"missing required stores: {sorted(missing)}")
        extra = set(names) - REQUIRED_STORES
        if extra:
            raise InvalidManifest(f"unknown stores: {sorted(extra)}")
        # Store stores in sorted order for determinism.
        object.__setattr__(self, "stores", tuple(sorted(self.stores, key=lambda s: s.name)))

    # -- canonical serialization ------------------------------------------

    def _content_dict(self) -> dict[str, object]:
        """Content that the manifest hash binds (no id/timestamp)."""
        return {
            "encryption": self.encryption,
            "rpo_target_seconds": self.rpo_target_seconds,
            "rto_target_seconds": self.rto_target_seconds,
            "stores": [s.to_dict() for s in self.stores],
        }

    def _full_dict(self) -> dict[str, object]:
        return {
            "created_at": self.created_at.isoformat(),
            "encryption": self.encryption,
            "manifest_id": self.manifest_id,
            "rpo_target_seconds": self.rpo_target_seconds,
            "rto_target_seconds": self.rto_target_seconds,
            "stores": [s.to_dict() for s in self.stores],
        }

    def canonical_json(self) -> str:
        """Deterministic JSON: sorted keys, compact separators, UTF-8."""
        return json.dumps(self._full_dict(), sort_keys=True, separators=(",", ":"))

    def manifest_hash(self) -> str:
        """sha256 over content only (excludes manifest_id and created_at)."""
        material = json.dumps(
            self._content_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(material).hexdigest()

    _KNOWN_TOP_LEVEL_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"manifest_id", "created_at", "stores", "rpo_target_seconds",
         "rto_target_seconds", "encryption"}
    )

    @classmethod
    def from_json(cls, text: str) -> BackupManifest:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidManifest(f"manifest is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise InvalidManifest("manifest must be a JSON object")
        unknown = set(data) - cls._KNOWN_TOP_LEVEL_FIELDS
        if unknown:
            raise InvalidManifest(
                f"manifest has unknown top-level fields: {sorted(unknown)}"
            )
        try:
            stores_raw = data["stores"]
        except KeyError as exc:
            raise InvalidManifest("manifest missing 'stores'") from exc
        if not isinstance(stores_raw, list):
            raise InvalidManifest("'stores' must be a list")
        stores = tuple(StoreEntry.from_dict(s) for s in stores_raw)
        try:
            created_at = datetime.fromisoformat(str(data["created_at"]))
        except (KeyError, ValueError) as exc:
            raise InvalidManifest(f"bad created_at: {exc}") from exc
        try:
            rpo = int(data.get("rpo_target_seconds", -1))
        except (TypeError, ValueError) as exc:
            raise InvalidManifest(
                f"rpo_target_seconds invalid: {exc}"
            ) from exc
        try:
            rto = int(data.get("rto_target_seconds", -1))
        except (TypeError, ValueError) as exc:
            raise InvalidManifest(
                f"rto_target_seconds invalid: {exc}"
            ) from exc
        return cls(
            manifest_id=str(data.get("manifest_id", "")),
            created_at=created_at,
            stores=stores,
            rpo_target_seconds=rpo,
            rto_target_seconds=rto,
            encryption=str(data.get("encryption", "none")),
        )

    # -- verification ------------------------------------------------------

    def store_entry(self, name: str) -> StoreEntry:
        for s in self.stores:
            if s.name == name:
                return s
        raise InvalidManifest(f"manifest does not cover store {name!r}")

    def verify_artifact(self, name: str, content: bytes) -> bool:
        """True iff content matches the recorded digest and size for a store."""
        entry = self.store_entry(name)
        if len(content) != entry.byte_size:
            return False
        return hashlib.sha256(content).hexdigest() == entry.sha256
