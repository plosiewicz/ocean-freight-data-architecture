"""Wave 0 stub — GRAPH-02 (UC3): chokepoint closure filter + reachability delta.

Offline logic test over a tiny in-memory edge fixture (no live cluster). Pins the
closure-helper contract for `aql/uc3_closure_unreachable.aql` + its Python driver
(Wave 3): closing a chokepoint must EXCLUDE the lane `_key`s transiting it
(reversible FILTER — never DELETE, D-09 so scenarios run back-to-back), and the
baseline-vs-closed reachability count must DIFFER when a closure removes lanes.

The closure-filter helper is built in Wave 3; this is a real assertion against it,
so it reports RED until then (skip-as-RED on ImportError).
"""

from __future__ import annotations

import pytest


def _import_closure():
    try:
        from analytics import uc3_closure  # noqa: F401
    except ImportError as exc:  # pragma: no cover - RED until Wave 3
        pytest.skip(f"analytics.uc3_closure not built yet (Wave 3): {exc}")
    return uc3_closure


# Tiny in-memory network: 3 lanes, SUEZ closure should drop the two SUEZ lanes.
_TRANSITS = {
    "L_USNYC_DEHAM": "SUEZ",
    "L_USNYC_CNSHA": "SUEZ",
    "L_USLAX_CNSHA": "PANAMA",
}


def test_closure_excludes_transiting_lanes():
    """Closing SUEZ excludes exactly the lanes whose transits_chokepoint == SUEZ."""
    uc3 = _import_closure()
    closed = uc3.closed_lane_keys(_TRANSITS, chokepoint="SUEZ")
    assert set(closed) == {"L_USNYC_DEHAM", "L_USNYC_CNSHA"}
    assert "L_USLAX_CNSHA" not in closed


def test_reachability_count_drops_under_closure():
    """Baseline reachable-lane count > closed count when a closure removes lanes."""
    uc3 = _import_closure()
    all_lanes = list(_TRANSITS)
    baseline = uc3.reachable_lane_count(all_lanes, closed=[])
    closed = uc3.closed_lane_keys(_TRANSITS, chokepoint="SUEZ")
    after = uc3.reachable_lane_count(all_lanes, closed=closed)
    assert baseline == 3
    assert after < baseline
