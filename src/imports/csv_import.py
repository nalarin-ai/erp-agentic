"""Generic safe import contract (MIG-001, R-005/R-008).

CSV-only fixture importer with strict limits, formula neutralization,
dedupe, redacted errors, and a zero-write dry-run. XLSX and other formats
are rejected fail-closed until a future task adds a sandboxed parser.
Synthetic opaque refs only; no network, no provider writes.

Deferred (MIG-QA-03): encryption/TTL/purge of persisted payloads belongs to
the persistent-evidence lane — this fixture lane is in-memory only, so
nothing persists to purge. Quarantine is a hard-reject (no quarantined
residue is retained).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
import io
import zipfile

#: Maximum decompression ratio accepted for zip containers (zip-bomb guard).
_MAX_DECOMPRESSION_RATIO = 100
_FORMULA_PREFIXES = ("=", "+", "-", "@")


class ImportRejected(RuntimeError):
    """The import payload violates a hard safety limit (fail-closed)."""


@dataclass(frozen=True, slots=True)
class ImportSummary:
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    quarantined: int
    provider_writes: int
    preview: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)


from src.imports.batch import BatchResult, FixtureBatchStore, ReversalResult


class SafeCsvImporter:
    """Bounded, zero-write CSV importer for synthetic fixture batches."""

    def __init__(self, *, max_bytes: int = 1_048_576, max_rows: int = 10_000) -> None:
        if max_bytes <= 0 or max_rows <= 0:
            raise ValueError("limits must be positive")
        self._max_bytes = max_bytes
        self._max_rows = max_rows
        self._batches = FixtureBatchStore()

    # -- public surface ----------------------------------------------------------

    def dry_run(self, payload: bytes) -> ImportSummary:
        """Validate and summarize without any provider write."""
        raw = self._unpack(payload)
        if len(raw) > self._max_bytes:
            raise ImportRejected("payload exceeds byte limit")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ImportRejected("payload is not valid UTF-8") from None
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            raise ImportRejected("empty payload")
        if len(rows) - 1 > self._max_rows:
            raise ImportRejected("payload exceeds row limit")
        header = rows[0]
        for cell in header:
            self._reject_traversal(cell)
        body = rows[1:]
        accepted: list[tuple[str, ...]] = []
        errors: list[str] = []
        seen: set[str] = set()
        duplicates = 0
        rejected = 0
        for row in body:
            if not any(cell.strip() for cell in row):
                continue
            key = row[0].strip() if row else ""
            if key in seen:
                duplicates += 1
                continue
            try:
                self._validate_row(row)
            except ImportRejected as exc:
                rejected += 1
                errors.append(str(exc))
                continue
            seen.add(key)
            accepted.append(tuple(self._neutralize(cell) for cell in row))
        return ImportSummary(
            accepted_rows=len(accepted),
            rejected_rows=rejected,
            duplicate_rows=duplicates,
            quarantined=0,
            provider_writes=0,
            preview=tuple(accepted[:10]),
            errors=tuple(errors),
        )

    # -- commit / reversal (bounded fixture batch) --------------------------------

    def commit_batch(self, payload: bytes) -> BatchResult:
        """Commit a validated batch: counts provider writes and reconciles."""
        summary = self.dry_run(payload)
        rows = summary.preview  # already validated + neutralized
        return self._batches.commit(rows)

    def reverse_batch(self, batch_ref: str) -> ReversalResult:
        """Compensating reversal of a committed batch; never destructive."""
        return self._batches.reverse(batch_ref)

    # -- internals -----------------------------------------------------------------

    def _unpack(self, payload: bytes) -> bytes:
        """Accept raw CSV; for zip containers enforce a decompression cap.

        XLSX-style multi-entry archives are rejected fail-closed (no sandboxed
        spreadsheet parser in this lane); unreadable/corrupt containers raise
        ``ImportRejected`` rather than leaking a partial parse.
        """
        if zipfile.is_zipfile(io.BytesIO(payload)):
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                    infos = zf.infolist()
                    if len(infos) != 1:
                        raise ImportRejected("zip container must hold exactly one file")
                    info = infos[0]
                    # MIG-QA-02: entry filename is traversal-checked even though
                    # the payload is only returned in-memory (never written to
                    # disk in this lane) — the guard keeps the contract safe if
                    # a future lane ever persists the unpacked content.
                    self._reject_traversal(info.filename)
                    if info.file_size > self._max_bytes:
                        raise ImportRejected("decompressed payload exceeds byte limit")
                    if info.compress_size > 0 and (
                        info.file_size / info.compress_size > _MAX_DECOMPRESSION_RATIO
                    ):
                        raise ImportRejected("decompression ratio limit exceeded")
                    return zf.read(info.filename)
            except zipfile.BadZipFile:
                raise ImportRejected("unreadable zip container") from None
        return payload

    def _reject_traversal(self, cell: str) -> None:
        if ".." in cell or cell.startswith(("/", "\\")):
            raise ImportRejected("unsafe path-like header cell")

    def _validate_row(self, row: list[str]) -> None:
        if len(row) < 4:
            raise ImportRejected("row rejected: insufficient columns")
        amount = row[2].strip()
        try:
            from decimal import Decimal
            Decimal(amount)
        except Exception:
            # Redacted: never echo the raw cell value.
            raise ImportRejected("row rejected: invalid amount format") from None

    def _neutralize(self, cell: str) -> str:
        stripped = cell.strip()
        if stripped.startswith(_FORMULA_PREFIXES):
            return "'" + stripped
        return stripped
