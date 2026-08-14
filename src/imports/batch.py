"""Bounded fixture batch commit + reversal for imports (MIG-001).

The commit path counts provider writes (unlike dry_run) and produces a
reconciled result; reversal is always a compensating record, never a
destructive delete. Synthetic opaque refs only.
"""
from __future__ import annotations

from dataclasses import dataclass
import itertools


@dataclass(frozen=True, slots=True)
class BatchResult:
    batch_ref: str
    posted: int
    reconciled: int
    provider_writes: int
    unreconciled_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReversalResult:
    batch_ref: str
    reversed_count: int
    compensating: bool
    destructive: bool


_BATCH_SEQ = itertools.count(1)


class FixtureBatchStore:
    """In-memory batch ledger proving the commit/reversal contract."""

    def __init__(self) -> None:
        self._posted: dict[str, tuple[tuple[str, ...], ...]] = {}
        self._reversed: dict[str, int] = {}

    def commit(self, rows: tuple[tuple[str, ...], ...]) -> BatchResult:
        batch_ref = f"IMP-{next(_BATCH_SEQ):06d}"
        self._posted[batch_ref] = rows
        return BatchResult(
            batch_ref=batch_ref,
            posted=len(rows),
            reconciled=len(rows),
            provider_writes=len(rows),
            unreconciled_refs=(),
        )

    def reverse(self, batch_ref: str) -> ReversalResult:
        rows = self._posted.get(batch_ref)
        if rows is None:
            raise KeyError(f"unknown batch {batch_ref}")
        self._reversed[batch_ref] = len(rows)
        return ReversalResult(
            batch_ref=batch_ref,
            reversed_count=len(rows),
            compensating=True,
            destructive=False,
        )
