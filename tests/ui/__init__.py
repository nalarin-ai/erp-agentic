"""Tests for the ui layer.

This package is named ``ui`` when discovered with ``-s tests`` (top-level
dir = tests/), which would shadow the real top-level ``ui/`` source package.
Extend ``__path__`` so imports like ``ui.invoice_review`` keep resolving to
the real source tree regardless of discovery mode.
"""
from __future__ import annotations

import pathlib

_ROOT_UI = pathlib.Path(__file__).resolve().parent.parent.parent / "ui"
if _ROOT_UI.is_dir():
    __path__.append(str(_ROOT_UI))  # noqa: F821
