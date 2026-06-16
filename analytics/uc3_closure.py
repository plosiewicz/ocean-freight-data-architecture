"""UC3 (GRAPH-02) — chokepoint exposure + closure analytics, Python API.

Thin use-case facade over ``lib.graph_queries`` encoding the D-12 reframe — UC3 is
THREE components, not a single "what becomes unreachable" assertion:

  (a) **transit-share %** per chokepoint — ``aql/uc3_chokepoint_share.aql`` via
      :func:`run_transit_share` (unchanged).
  (b) **criticality ranking** — GAE / NetworkX betweenness in
      ``analytics/run_criticality.py`` (unchanged here).
  (c) **reroute-impact** — :func:`run_reroute_impact`: closing a chokepoint forces
      its transiting lanes onto a longer alternative; the summed reroute delta
      (extra ``transit_time_hours``) is the honest finding for a meshed network
      (closures force DETOURS, they rarely disconnect). Reuses the UC4 weighted
      ``SHORTEST_PATH`` machinery over the ``route`` edge collection (D-10).

**Genuine unreachability** (:func:`run_closure`) is reported ONLY where it truly
occurs — **GIBRALTAR**, the one featured chokepoint that fragments this US-centric
topology. **SUEZ / PANAMA** are reroute-impact (they do NOT fragment — Far-East
ports stay reachable via trans-Pacific + US<->US proforma routes). **MALACCA** shows
transit-share 0 / criticality 0 because US-trade lanes don't transit it (an
Asia-Europe chokepoint) — a CORRECT honest finding, never fabricated into a US lane.

Closure is REVERSIBLE — a FILTER/prune over the ``route`` edge collection, never a
REMOVE/DELETE — so scenarios run back-to-back without mutating shared graph state
(D-09 / threat T-06-07). All UC params are AQL bind variables (threat T-06-06).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from lib.graph_queries import (
    closed_lane_keys as closed_lane_keys,
    disabled_lane_keys_for_chokepoint as disabled_lane_keys_for_chokepoint,
    reachable_lane_count as reachable_lane_count,
    reroute_delta as reroute_delta,
    run_query,
)

CLOSURE_QUERY = "uc3_closure_unreachable"
SHARE_QUERY = "uc3_chokepoint_share"
REROUTE_IMPACT_QUERY = "uc3_reroute_impact"

# Featured chokepoints and their UC3 disposition (D-12 reframe):
#   SUEZ / PANAMA  -> reroute-impact (delta > 0; do NOT fragment)
#   GIBRALTAR      -> genuine unreachability (the one chokepoint that fragments)
#   MALACCA        -> transit-share / criticality 0 (documented honest zero)
FEATURED_CHOKEPOINTS = ("SUEZ", "PANAMA", "MALACCA")
REROUTE_IMPACT_CHOKEPOINTS = ("SUEZ", "PANAMA")
FRAGMENTING_CHOKEPOINTS = ("GIBRALTAR",)
DOCUMENTED_ZERO_CHOKEPOINTS = ("MALACCA",)


def run_transit_share(*, db: Any = None) -> list[Any]:
    """Run the transit-share query (no binds) and return per-chokepoint rows."""
    return run_query(SHARE_QUERY, {}, db=db)


def run_closure(closed: str, *, maxhops: int = 200, db: Any = None) -> list[Any]:
    """Run the GENUINE-UNREACHABILITY closure for chokepoint ``closed`` (bind vars).

    Route-edge-scoped path-existence probe reserved for chokepoints that truly
    fragment the topology (GIBRALTAR). For each (origin, target) port pair it asks
    whether a path exists none of whose ``route`` edges transit ``closed`` (via
    K_SHORTEST_PATHS, ``@maxhops`` = the candidate-path enumeration cap). Returns
    per-origin ``reachable_count`` rows; a drop vs the baseline (a non-fragmenting
    ``closed``) is genuine fragmentation. SUEZ/PANAMA show NO drop (a reroute
    exists); GIBRALTAR drops (the European ports have no clean alternative).
    Reversible (FILTER, not delete).
    """
    return run_query(
        CLOSURE_QUERY,
        {"closed": closed, "maxhops": maxhops},
        db=db,
    )


def run_reroute_impact(
    closed: str,
    origin: str,
    dest: str,
    *,
    db: Any = None,
) -> dict[str, Any]:
    """Reroute-impact of closing ``closed`` on the ``origin``->``dest`` route (D-12c).

    Resolves the closed chokepoint's transiting ``lane_key``s (via the D-09 rule over
    the canonical LANES + US<->US proforma network) into ``@disabled_lanes``, then
    runs ``aql/uc3_reroute_impact.aql`` (the UC4 weighted-SHORTEST_PATH machinery)
    BASELINE (``@disabled_lanes = []``) vs REROUTE (the disabled set). Returns the
    baseline / reroute leg-hour lists and the summed ``delta`` (extra transit hours
    the closure imposes; > 0 = the honest reroute cost). All params bind variables.
    """
    from data_gen.network import LANES, US_US_LANES
    from lib.graph_loader import chokepoints_for_lane

    disabled = disabled_lane_keys_for_chokepoint(
        tuple(LANES) + tuple(US_US_LANES), chokepoints_for_lane, closed
    )
    origin_id = origin if "/" in origin else f"ports/{origin}"
    dest_id = dest if "/" in dest else f"ports/{dest}"

    baseline_rows = run_query(
        REROUTE_IMPACT_QUERY,
        {"origin": origin_id, "dest": dest_id, "disabled_lanes": []},
        db=db,
    )
    reroute_rows = run_query(
        REROUTE_IMPACT_QUERY,
        {"origin": origin_id, "dest": dest_id, "disabled_lanes": disabled},
        db=db,
    )
    baseline_legs = [float(r.get("leg_hours") or 0.0) for r in baseline_rows]
    reroute_legs = [float(r.get("leg_hours") or 0.0) for r in reroute_rows]
    return {
        "closed": closed,
        "origin": origin_id,
        "dest": dest_id,
        "disabled_lanes": disabled,
        "baseline_legs": baseline_legs,
        "reroute_legs": reroute_legs,
        "delta": reroute_delta(baseline_legs, reroute_legs),
    }


__all__ = [
    "closed_lane_keys",
    "disabled_lane_keys_for_chokepoint",
    "reachable_lane_count",
    "reroute_delta",
    "run_transit_share",
    "run_closure",
    "run_reroute_impact",
    "CLOSURE_QUERY",
    "SHARE_QUERY",
    "REROUTE_IMPACT_QUERY",
    "FEATURED_CHOKEPOINTS",
    "REROUTE_IMPACT_CHOKEPOINTS",
    "FRAGMENTING_CHOKEPOINTS",
    "DOCUMENTED_ZERO_CHOKEPOINTS",
]


# Re-export the pure helper signatures so static checkers see them with types.
def _typed_closed_lane_keys(
    transits: Mapping[str, str], chokepoint: str
) -> list[str]:  # pragma: no cover - documentation alias
    return closed_lane_keys(transits, chokepoint)


def _typed_reachable_lane_count(
    all_lanes: Iterable[str], *, closed: Iterable[str]
) -> int:  # pragma: no cover - documentation alias
    return reachable_lane_count(all_lanes, closed=closed)
