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
    """Equal BQ dim rows and Arango REAL-subset vertex counts reconcile (parity OK).

    06-06: synthetic foreign ports are additive in the `ports` collection, so gate 17
    feeds the REAL-provenance vertex count (4 US ports), NOT the raw collection count.
    Parity stays EXACT equality on the shared real subset.
    """
    xs = _import_xstore()
    pairs = [("dim_port", 4, "ports", 4), ("dim_vessel", 1545, "vessels", 1545)]
    ok, mismatches = xs.check_count_parity(pairs)
    assert ok is True
    assert mismatches == []


def test_count_parity_passes_when_raw_ports_larger_but_real_subset_matches():
    """Parity PASSES when BQ dim_port == real ports vertices even though the raw
    `ports` collection is larger (synthetic foreign ports present) — the gate counts
    the real subset, so the additive synthetic ports are correctly excluded."""
    xs = _import_xstore()
    # The gate already filtered to provenance=real (4); the raw collection is 9.
    real_port_vertices = 4
    pairs = [("dim_port", 4, "ports", real_port_vertices)]
    ok, mismatches = xs.check_count_parity(pairs)
    assert ok is True
    assert mismatches == []


def test_count_parity_fails_when_a_real_port_is_dropped_or_duplicated():
    """Parity still FAILS (bridge broken) if a REAL port is dropped or duplicated,
    independent of the additive synthetic foreign ports."""
    xs = _import_xstore()
    # A real port dropped: BQ has 4, real vertices only 3.
    dropped = [("dim_port", 4, "ports", 3)]
    ok, mismatches = xs.check_count_parity(dropped)
    assert ok is False
    assert any("dim_port" in m and "ports" in m for m in mismatches)
    # A real port duplicated: BQ has 4, real vertices 5.
    dup = [("dim_port", 4, "ports", 5)]
    ok2, mismatches2 = xs.check_count_parity(dup)
    assert ok2 is False
    assert any("dim_port" in m for m in mismatches2)


def test_count_parity_flags_mismatch():
    """A BQ-vs-Arango count mismatch is flagged (broken shared-key bridge)."""
    xs = _import_xstore()
    pairs = [("dim_carrier", 8, "carriers", 7)]  # one carrier vertex missing
    ok, mismatches = xs.check_count_parity(pairs)
    assert ok is False
    assert any("dim_carrier" in m and "carriers" in m for m in mismatches)


def test_suez_lane_keys_uses_rule_over_canonical_network():
    """suez_lane_keys selects exactly the rule's Suez lanes from the canonical net."""
    xs = _import_xstore()
    from data_gen.network import LANES
    from lib.graph_loader import chokepoints_for_lane

    keys = xs.suez_lane_keys(LANES, chokepoints_for_lane)
    # Cross-check against an independent recomputation of the same rule.
    expected = [
        f"{o}__{d}" for (o, d) in LANES if "SUEZ" in chokepoints_for_lane(o, d)
    ]
    assert keys == expected
    assert len(keys) > 0  # the far-east<->US-east lanes transit Suez
    # The key convention matches lib.graph_loader.lane_key (the shared bridge).
    from lib.graph_loader import lane_key

    o, d = LANES[0]
    assert lane_key(o, d) == f"{o}__{d}"


def test_semantic_suez_passes_when_arango_matches_rule():
    """Arango Suez edges == rule-expected count reconciles (semantic parity OK)."""
    xs = _import_xstore()
    # 12 rule-expected Suez lanes, 12 Arango edges, BQ overlaps on 3 served lanes.
    ok, mismatches = xs.check_semantic_suez(
        expected_suez_lane_count=12,
        arango_suez_edge_count=12,
        bq_lane_key_overlap=3,
    )
    assert ok is True
    assert mismatches == []


def test_semantic_suez_flags_arango_drift():
    """A graph that projected the wrong number of Suez edges is flagged."""
    xs = _import_xstore()
    ok, mismatches = xs.check_semantic_suez(
        expected_suez_lane_count=12,
        arango_suez_edge_count=11,  # one transit edge missing in the graph
        bq_lane_key_overlap=3,
    )
    assert ok is False
    assert any("SUEZ" in m and "11" in m and "12" in m for m in mismatches)
