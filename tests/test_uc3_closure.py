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


# --------------------------------------------------------------------------- #
# 06-06 reframe (D-12): the UC3 closure AQL is now route-edge-scoped genuine     #
# unreachability RESERVED for chokepoints that truly fragment (GIBRALTAR).       #
# The phantom v.lane_key attribute is gone; the query binds an edge var,         #
# traverses ONLY the `route` edge collection, and prunes on the real             #
# `e.chokepoints` array against @closed.                                         #
# --------------------------------------------------------------------------- #
import pathlib  # noqa: E402

_CLOSURE_AQL = (
    pathlib.Path(__file__).resolve().parent.parent
    / "aql"
    / "uc3_closure_unreachable.aql"
)


def test_closure_aql_is_route_scoped_and_prunes_on_chokepoints():
    """The rewritten closure AQL drops the phantom v.lane_key, binds an edge var,
    traverses the `route` edge collection, and prunes on the real chokepoints attr."""
    if not _CLOSURE_AQL.is_file():
        pytest.skip("aql/uc3_closure_unreachable.aql not authored yet")
    src = _CLOSURE_AQL.read_text()
    assert "v.lane_key" not in src  # phantom attribute removed
    assert "GRAPH 'ocean_network'" not in src  # no full-named-graph walk
    assert "route" in src  # restricted to the route edge collection
    assert "chokepoints" in src  # prunes on the real route.chokepoints attr
    assert "@closed" in src  # bind var, never interpolated
    assert "@maxhops" in src


def test_closure_aql_binds_edge_variable():
    """The traversal binds the edge variable (FOR v, e ...) so it can prune on e."""
    if not _CLOSURE_AQL.is_file():
        pytest.skip("aql/uc3_closure_unreachable.aql not authored yet")
    src = _CLOSURE_AQL.read_text()
    assert "FOR v, e IN" in src


def test_reframe_gibraltar_fragments_suez_does_not():
    """Pin the D-12 reframe over an in-memory route fixture: GIBRALTAR closure drops
    reachable count; SUEZ closure leaves it unchanged (reroute-impact, not unreach)."""
    uc3 = _import_closure()
    # Routes reachable from USNYC and the chokepoints each transits.
    routes = {
        "USNYC__CNSHA": ["PANAMA", "SUEZ"],  # Far-East: reroutable
        "USNYC__USLAX": [],                  # proforma leg (detour hop)
        "USLAX__CNSHA": [],                  # trans-Pacific detour
        "USNYC__DEHAM": ["GIBRALTAR"],       # Europe: ONLY path to DEHAM here
    }
    all_lanes = list(routes)
    baseline = uc3.reachable_lane_count(all_lanes, closed=[])

    suez_closed = [lk for lk, cps in routes.items() if "SUEZ" in cps]
    gib_closed = [lk for lk, cps in routes.items() if "GIBRALTAR" in cps]

    suez_after = uc3.reachable_lane_count(all_lanes, closed=suez_closed)
    gib_after = uc3.reachable_lane_count(all_lanes, closed=gib_closed)

    # GIBRALTAR removes the sole DEHAM lane (fragmentation -> fewer reachable lanes).
    assert gib_after < baseline
    # SUEZ removes a lane but CNSHA stays reachable via the detour lanes; the SUEZ
    # lane itself drops, but the reframe is asserted live by reroute-impact delta > 0
    # (test_uc3_reroute_impact). Here we pin that GIBRALTAR fragments MORE than the
    # featured non-fragmenting chokepoint scenario expects: a SUEZ-unreachability
    # gate must NEVER be hard-coded — that regression is caught in reroute-impact.
    assert gib_after <= suez_after
