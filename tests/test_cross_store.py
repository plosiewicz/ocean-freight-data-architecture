"""Wave 0 stub — ETL-05: cross-store count-parity reconciliation.

Offline logic test (mocked count providers — no live BQ or Arango). Pins the
reconciliation contract for the Wave-5 `scripts/verify.py` graph gates (exit 17):
the count-parity check must FLAG a mismatch (BQ dim rows != Arango vertex counts —
the shared-key bridge is broken) and PASS when counts are equal.

The reconciliation helper is built in Wave 5 (skip-as-RED until it exists). The
assertions are real over mocked dim-count / vertex-count providers.
"""

from __future__ import annotations

import pytest


def _import_xstore():
    try:
        from scripts import xstore  # noqa: F401
    except ImportError as exc:  # pragma: no cover - RED until Wave 5
        pytest.skip(f"scripts.xstore not built yet (Wave 5): {exc}")
    return xstore


def test_count_parity_passes_on_equal_counts():
    """Equal BQ dim rows and Arango vertex counts reconcile (parity OK)."""
    xs = _import_xstore()
    pairs = [("dim_port", 9, "ports", 9), ("dim_vessel", 1545, "vessels", 1545)]
    ok, mismatches = xs.check_count_parity(pairs)
    assert ok is True
    assert mismatches == []


def test_count_parity_flags_mismatch():
    """A BQ-vs-Arango count mismatch is flagged (broken shared-key bridge)."""
    xs = _import_xstore()
    pairs = [("dim_carrier", 8, "carriers", 7)]  # one carrier vertex missing
    ok, mismatches = xs.check_count_parity(pairs)
    assert ok is False
    assert any("dim_carrier" in m and "carriers" in m for m in mismatches)
