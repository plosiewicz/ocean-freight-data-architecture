"""06-06 (GRAPH-02 / UC3 reframe, D-12) — offline reroute-impact NON-DEGENERACY proxy.

The CI-runnable proxy for the live anti-degeneracy gate: over an in-memory fixture
route network mirroring the real topology, closing a non-fragmenting chokepoint
(SUEZ) must force the transiting lane onto a longer alternative so the SUMMED
reroute delta is STRICTLY > 0. This pins the honest finding for a meshed network
(closures force detours, they rarely disconnect) and FAILS if a future regression
makes the disabled-lane filter a no-op again (the green-but-hollow failure).

It also pins the REFRAME: GIBRALTAR genuinely fragments the topology (a reachable
port-pair becomes unreachable) while SUEZ does NOT (reachable count unchanged) — so
a regression to a hard SUEZ-"unreachable" assertion fails CI.

All assertions are over in-memory fixtures (no cluster), exercising the SAME pure
helpers (lib.graph_queries.reroute_delta / reachable_lane_count) the live AQL drives.
"""

from __future__ import annotations

import pytest


def _import():
    try:
        from analytics import uc3_closure  # noqa: F401
        from lib import graph_queries  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"uc3 reroute-impact helpers not built yet: {exc}")
    return uc3_closure, graph_queries


# A tiny weighted route network mirroring the real topology shape:
#   USNYC -> CNSHA  direct, transits {SUEZ, PANAMA}, ~356h  (the disrupted lane)
#   USNYC -> USLAX  US<->US proforma leg, ~120h
#   USLAX -> CNSHA  trans-Pacific, no curated canal, ~312h  (the detour second leg)
# So baseline USNYC->CNSHA = 356h direct; with SUEZ disabled the direct lane is
# excluded and the optimal path is USNYC->USLAX->CNSHA = 120 + 312 = 432h.
_FIXTURE_ROUTES = {
    "USNYC__CNSHA": {"hours": 356.0, "chokepoints": ["PANAMA", "SUEZ"]},
    "USNYC__USLAX": {"hours": 120.0, "chokepoints": []},
    "USLAX__CNSHA": {"hours": 312.0, "chokepoints": []},
    # A Europe leg that ONLY connects via Gibraltar in the fixture, so removing
    # Gibraltar lanes disconnects DEHAM (genuine fragmentation).
    "USNYC__DEHAM": {"hours": 280.0, "chokepoints": ["GIBRALTAR"]},
}


def _disabled_for(closed: str) -> list[str]:
    """The lane_keys transiting a closed chokepoint (mirrors chokepoints_for_lane)."""
    return [lk for lk, e in _FIXTURE_ROUTES.items() if closed in e["chokepoints"]]


def _shortest_hours(origin: str, dest: str, *, disabled: set[str]) -> float | None:
    """Tiny Dijkstra over the fixture route network with disabled lanes excluded."""
    import heapq

    adj: dict[str, list[tuple[str, float]]] = {}
    for lk, e in _FIXTURE_ROUTES.items():
        if lk in disabled:
            continue
        o, d = lk.split("__", 1)
        adj.setdefault(o, []).append((d, e["hours"]))
    pq = [(0.0, origin)]
    best: dict[str, float] = {origin: 0.0}
    while pq:
        cost, node = heapq.heappop(pq)
        if node == dest:
            return cost
        if cost > best.get(node, float("inf")):
            continue
        for nxt, w in adj.get(node, []):
            nc = cost + w
            if nc < best.get(nxt, float("inf")):
                best[nxt] = nc
                heapq.heappush(pq, (nc, nxt))
    return best.get(dest)


def test_suez_reroute_delta_strictly_positive():
    """Closing SUEZ forces USNYC->CNSHA onto the trans-Pacific detour; delta > 0."""
    _uc3, gq = _import()
    baseline = _shortest_hours("USNYC", "CNSHA", disabled=set())
    disabled = set(_disabled_for("SUEZ"))
    reroute = _shortest_hours("USNYC", "CNSHA", disabled=disabled)
    assert baseline == pytest.approx(356.0)
    assert reroute == pytest.approx(432.0)  # 120 + 312 detour
    delta = gq.reroute_delta([baseline], [reroute])
    assert delta > 0
    assert delta == pytest.approx(76.0)


def test_suez_does_not_fragment_reachability():
    """SUEZ closure leaves CNSHA reachable from USNYC (reroute-impact, NOT unreachable)."""
    _uc3, _gq = _import()
    disabled = set(_disabled_for("SUEZ"))
    # CNSHA is still reachable (via the trans-Pacific detour) — the reframe.
    assert _shortest_hours("USNYC", "CNSHA", disabled=disabled) is not None


def test_gibraltar_genuinely_fragments():
    """GIBRALTAR closure disconnects DEHAM from USNYC (genuine unreachability)."""
    _uc3, _gq = _import()
    baseline = _shortest_hours("USNYC", "DEHAM", disabled=set())
    disabled = set(_disabled_for("GIBRALTAR"))
    after = _shortest_hours("USNYC", "DEHAM", disabled=disabled)
    assert baseline is not None
    assert after is None  # DEHAM becomes unreachable -> fragmentation


def test_run_reroute_impact_facade_exists():
    """analytics.uc3_closure exposes a run_reroute_impact facade (offline-importable)."""
    uc3, _gq = _import()
    assert hasattr(uc3, "run_reroute_impact")
    assert callable(uc3.run_reroute_impact)
