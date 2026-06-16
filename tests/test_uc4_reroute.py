"""Wave 0 stub — GRAPH-03 (UC4): weighted SHORTEST_PATH reroute delta.

Two offline contracts pinned for Wave 3:

  * the reroute-delta math — ``delta = SUM(reroute legs) - SUM(baseline legs)`` over
    per-leg ``transit_time_hours`` (computed in Python per D-10);
  * the UC4 AQL file carries ``weightAttribute: 'transit_time_hours'`` (the weighted
    path discipline; ``defaultWeight: 1e9`` and bind vars — never f-stringed, V5).

The delta helper is built in Wave 3 (skip-as-RED until it exists). The AQL string
assertion is skip-as-RED until `aql/uc4_reroute_shortest_path.aql` is authored.
"""

from __future__ import annotations

import pathlib

import pytest

_AQL_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "aql"
    / "uc4_reroute_shortest_path.aql"
)


def _import_reroute():
    try:
        from analytics import uc4_reroute  # noqa: F401
    except ImportError as exc:  # pragma: no cover - RED until Wave 3
        pytest.skip(f"analytics.uc4_reroute not built yet (Wave 3): {exc}")
    return uc4_reroute


def test_reroute_delta_is_reroute_minus_baseline():
    """delta = SUM(reroute legs) - SUM(baseline legs) over transit_time_hours."""
    uc4 = _import_reroute()
    baseline_legs = [100.0, 50.0]   # 150
    reroute_legs = [120.0, 60.0, 40.0]  # 220
    delta = uc4.reroute_delta(baseline_legs, reroute_legs)
    assert delta == pytest.approx(70.0)


def test_uc4_aql_uses_transit_time_weight_attribute():
    """The UC4 AQL pins weightAttribute: 'transit_time_hours' (weighted path)."""
    if not _AQL_PATH.is_file():
        pytest.skip("aql/uc4_reroute_shortest_path.aql not authored yet (Wave 3)")
    src = _AQL_PATH.read_text()
    assert "weightAttribute: 'transit_time_hours'" in src


def test_uc4_aql_disables_lanes_by_real_lane_key():
    """The UC4 disabled-lane exclusion binds the REAL e.lane_key attribute (06-06)."""
    if not _AQL_PATH.is_file():
        pytest.skip("aql/uc4_reroute_shortest_path.aql not authored yet")
    src = _AQL_PATH.read_text()
    assert "e.lane_key NOT IN @disabled_lanes" in src


def test_uc3_reroute_impact_aql_is_allow_listed_and_uses_route_shortest_path():
    """The NEW uc3_reroute_impact query is allow-listed and reuses UC4 machinery."""
    from lib import graph_queries

    src = graph_queries.load_aql("uc3_reroute_impact")  # raises if not allow-listed
    assert "SHORTEST_PATH" in src
    assert "@disabled_lanes" in src
    assert "route" in src  # restricted to the route edge collection
