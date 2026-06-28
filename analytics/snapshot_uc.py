"""analytics/snapshot_uc.py — credential-free UC3/UC4 snapshot SOURCE functions.

The Phase-7 (DEL-01) snapshot contract for the two GRAPH use cases. Each function
returns a PLAIN, credential-free :class:`dict` (only counts / floats / strings /
lists — threat T-06-08 / T-07-01) assembled by DELEGATING to the existing
source-of-truth runners in ``analytics/uc3_closure.py`` and
``analytics/uc4_reroute.py``. Both the freezer (``scripts/freeze_uc.py``) and the
07-03 demo notebook read this contract, so the shapes here are the single source
of truth for the UC3/UC4 demo answers.

Credential safety (Shared Pattern "Credential safety", threats T-06-01 / T-06-08):
this module NEVER constructs an ArangoDB client and NEVER logs a secret. All cluster
access flows through the runners' existing ``lib.arango_client.get_db`` delegation
(``run_query``); an optional ``db`` handle may be passed in (so a caller that already
holds a connection — the freezer — reuses it), but it is opaque here. No
``ARANGO_*`` / password / JWT value is ever read, embedded, or returned.

Versioned-query discipline (threat T-06-06 / ASVS V5): every query parameter
(``origin`` / ``dest`` / ``closed`` / ``disabled_lanes``) is passed through the
runners as an AQL BIND variable — no value is f-string-interpolated into a query.

D-12 reframe (UC3 is THREE components, not one "unreachable" assertion):
  - ``transit_share``        — per-chokepoint transit-share rows (run_transit_share).
  - ``reroute_impact_suez``  — closing SUEZ on USNYC->CNSHA forces a longer detour;
                               the summed reroute ``delta`` (> 0) is the honest finding.
  - ``closure_gibraltar``    — GIBRALTAR is the ONE chokepoint that genuinely
                               fragments this US-centric topology; the snapshot carries
                               the OPEN-baseline vs GIBRALTAR-closed reachable-port
                               counts so the closure-induced DROP is recoverable
                               (29 -> fewer, the deck-citable non-degeneracy proof).
"""

from __future__ import annotations

from typing import Any

from analytics import uc3_closure, uc4_reroute
from lib.graph_queries import disabled_lane_keys_for_chokepoint, reroute_delta

# The featured demo route (mirrors scripts/verify.py UC_DEMO_ORIGIN/DEST): USNYC->CNSHA
# transits SUEZ + PANAMA, so closing SUEZ forces the trans-Pacific detour (delta > 0).
DEMO_ORIGIN = "USNYC"
DEMO_DEST = "CNSHA"
# The reroute-impact chokepoint frozen for the deck (D-12: SUEZ is reroute-impact, the
# +76.2h cited figure). Genuine fragmentation is GIBRALTAR (closure_gibraltar below).
REROUTE_IMPACT_CHOKEPOINT = "SUEZ"
FRAGMENTING_CHOKEPOINT = "GIBRALTAR"
# A sentinel "closed" chokepoint that no lane transits — the closure OPEN baseline
# (mirrors verify.UC_OPEN_SENTINEL). Its total reachable count is the unconstrained
# baseline the GIBRALTAR-closed count is compared against.
OPEN_SENTINEL = "__NONE_OPEN__"


def _total_reachable(rows: list[Any]) -> int:
    """Sum the per-origin ``reachable_count`` from a closure result (defensive)."""
    return sum(int(r.get("reachable_count", 0) or 0) for r in rows)


# searoute AVOID set that forces a polyline THROUGH the named chokepoint, so a lane
# disabled by closing that chokepoint draws as a line that visibly transits it
# (geometry is cosmetic only). SUEZ -> avoid Panama; PANAMA -> avoid Suez. For
# GIBRALTAR (and any other) the natural shortest sea-route already takes the Med
# approach, so no restriction is needed.
_CHOKEPOINT_RESTRICT: dict[str, tuple[str, ...]] = {
    "SUEZ": ("panama",),
    "PANAMA": ("suez",),
}


def _disabled_lane_paths(
    disabled_lanes: list[str], chokepoint: str
) -> list[dict[str, Any]]:
    """Bake a per-lane sea-route polyline for each disabled ``A__B`` lane (REQ-14-2/4).

    Splits each ``A__B`` lane key to its endpoint port centroids and routes a
    cosmetic searoute polyline THROUGH the closed ``chokepoint`` (via the per-
    chokepoint restrict). Coords come pre-rounded/normalized from
    ``searoute_geometry.polyline_for``; the analytic counts/deltas are untouched.
    Order-stable (follows ``disabled_lanes`` order).
    """
    from lib.searoute_geometry import centroid_for, polyline_for

    restrict = _CHOKEPOINT_RESTRICT.get(chokepoint, ())
    paths: list[dict[str, Any]] = []
    for lk in disabled_lanes:
        a, _, b = lk.partition("__")
        if not a or not b:
            continue
        paths.append(
            {
                "lane_key": lk,
                "waypoints": polyline_for(
                    centroid_for(a), centroid_for(b), restrict=restrict
                ),
            }
        )
    return paths


def snapshot_uc3(db: Any = None) -> dict[str, Any]:
    """Assemble the credential-free UC3 snapshot dict (transit-share + reroute + closure).

    Delegates to the existing ``analytics.uc3_closure`` runners (all params bound as
    AQL bind vars there). Returns ONLY counts / floats / strings / lists — no client
    or credential object. ``db`` is an optional already-open handle threaded through
    to the runners; it is never inspected here (credential opacity, T-06-08).
    """
    share_rows = uc3_closure.run_transit_share(db=db)
    transit_share = sorted(
        (
            {
                "chokepoint": str(r.get("chokepoint") or r.get("_key") or ""),
                "transiting_lanes": int(r.get("transiting_lanes", 0) or 0),
                "total_lanes": int(r.get("total_lanes", 0) or 0),
                "transit_share_pct": (
                    round(float(r["transit_share_pct"]), 12)
                    if r.get("transit_share_pct") is not None
                    else None
                ),
            }
            for r in share_rows
        ),
        key=lambda r: r["chokepoint"],
    )

    impact = uc3_closure.run_reroute_impact(
        REROUTE_IMPACT_CHOKEPOINT, DEMO_ORIGIN, DEMO_DEST, db=db
    )
    reroute_impact_suez = {
        "closed": str(impact["closed"]),
        "origin": str(impact["origin"]),
        "dest": str(impact["dest"]),
        "disabled_lanes": [str(x) for x in impact["disabled_lanes"]],
        "baseline_legs": [round(float(x), 12) for x in impact["baseline_legs"]],
        "reroute_legs": [round(float(x), 12) for x in impact["reroute_legs"]],
        "baseline_hours": round(float(sum(impact["baseline_legs"])), 12),
        "reroute_hours": round(float(sum(impact["reroute_legs"])), 12),
        "delta": round(float(impact["delta"]), 12),
    }

    # Genuine unreachability: OPEN baseline vs GIBRALTAR-closed reachable-port counts,
    # so the closure-induced DROP (29 -> fewer) is recoverable from the snapshot alone.
    # baseline_rows is the SHARED OPEN baseline — reused below by closure_by_chokepoint
    # (do NOT recompute the open baseline per chokepoint).
    baseline_rows = uc3_closure.run_closure(OPEN_SENTINEL, db=db)
    gib_rows = uc3_closure.run_closure(FRAGMENTING_CHOKEPOINT, db=db)
    closure_gibraltar = {
        "closed": FRAGMENTING_CHOKEPOINT,
        "open_reachable_total": _total_reachable(baseline_rows),
        "closed_reachable_total": _total_reachable(gib_rows),
        "open_origins": int(len(baseline_rows)),
        "closed_origins": int(len(gib_rows)),
    }

    # Per-chokepoint closure + reroute-impact (the 7-chokepoint generalization of the
    # single-Gibraltar / single-Suez story above). One entry per chokepoint present in
    # transit_share; the SHARED OPEN baseline (baseline_rows) is reused for open_* on
    # every entry. SUEZ/PANAMA carry a > 0 reroute delta on USNYC->CNSHA; GIBRALTAR
    # fragments (closed_reachable_total drops); the rest are inert (delta 0, no drop).
    open_total = _total_reachable(baseline_rows)
    open_origins = int(len(baseline_rows))
    closure_by_chokepoint = []
    for cp in (str(r["chokepoint"]) for r in transit_share):
        cp_rows = uc3_closure.run_closure(cp, db=db)
        cp_impact = uc3_closure.run_reroute_impact(cp, DEMO_ORIGIN, DEMO_DEST, db=db)
        disabled_lanes = [str(x) for x in cp_impact["disabled_lanes"]]
        closure_by_chokepoint.append(
            {
                "chokepoint": cp,
                "open_reachable_total": open_total,
                "closed_reachable_total": _total_reachable(cp_rows),
                "open_origins": open_origins,
                "closed_origins": int(len(cp_rows)),
                "reroute_baseline_hours": round(
                    float(sum(cp_impact["baseline_legs"])), 12
                ),
                "reroute_reroute_hours": round(
                    float(sum(cp_impact["reroute_legs"])), 12
                ),
                "reroute_delta_hours": round(float(cp_impact["delta"]), 12),
                "disabled_lane_count": int(len(disabled_lanes)),
                # REQ-14-2: the actual disabled-lane KEYS (not just the count) so the
                # map can highlight the affected lanes when a chokepoint is selected.
                "disabled_lanes": disabled_lanes,
                # REQ-14-4: baked cosmetic sea-route polyline per disabled lane.
                "disabled_lane_paths": _disabled_lane_paths(disabled_lanes, cp),
            }
        )
    closure_by_chokepoint.sort(key=lambda e: e["chokepoint"])

    return {
        "use_case": "UC3",
        "origin": DEMO_ORIGIN,
        "dest": DEMO_DEST,
        "transit_share": transit_share,
        "reroute_impact_suez": reroute_impact_suez,
        "closure_gibraltar": closure_gibraltar,
        "closure_by_chokepoint": closure_by_chokepoint,
    }


# --------------------------------------------------------------------------- #
# Curated UC4 disruption scenarios (REQ-14-6 / DECISION 3). Each closes ONE   #
# named canal (REQ-14-5) on a route that chokepoint actually serves.          #
#   * SUEZ      — the featured Asia->US-East pair USNYC->CNSHA (SUEZ-routed A1)#
#                 — non-fragmenting: a longer Pacific detour exists (delta>0). #
#   * PANAMA    — Europe->US-West DEHAM->USLAX (PANAMA-routed via the canal)   #
#                 — non-fragmenting: a longer detour exists (delta>0).         #
#   * GIBRALTAR — Europe->US-East DEHAM->USNYC — FRAGMENTING (PROJECT D-12):   #
#                 GIBRALTAR is assigned to EVERY Europe<->US lane, so closing  #
#                 it disconnects Europe entirely (no model reroute; the locked #
#                 genuine-unreachability 29->11 story). Its scenario tells the #
#                 FRAGMENTATION story: empty model reroute (delta == 0,        #
#                 reroute_available False) but a COSMETIC Cape-of-Good-Hope    #
#                 baseline polyline so the map still has geometry to draw.     #
# `restrict` is the searoute AVOID set that FORCES the scenario's baseline     #
# routing geometry (cosmetic only): a SUEZ-routed leg avoids Panama, a         #
# PANAMA-routed leg avoids Suez, the GIBRALTAR case forces the Cape (avoid     #
# both) since the Med approach it would otherwise take is what is closed.      #
# --------------------------------------------------------------------------- #
_UC4_SCENARIOS: tuple[dict[str, Any], ...] = (
    {"id": "suez", "label": "Suez Canal closed (Asia ↔ US-East)",
     "closed": "SUEZ", "origin": "USNYC", "dest": "CNSHA", "restrict": "panama",
     "fragmenting": False},
    {"id": "panama", "label": "Panama Canal closed (Europe ↔ US-West)",
     "closed": "PANAMA", "origin": "DEHAM", "dest": "USLAX", "restrict": "suez",
     "fragmenting": False},
    {"id": "gibraltar", "label": "Strait of Gibraltar closed (Europe ↔ US-East)",
     "closed": "GIBRALTAR", "origin": "DEHAM", "dest": "USNYC", "restrict": "panama,suez",
     "fragmenting": True},
)


def _port_id(code: str) -> str:
    return code if "/" in code else f"ports/{code}"


def _bare_code(port_id: str) -> str:
    return port_id.split("/", 1)[-1]


def _waypoints_for_path(rows: list[Any], restrict: tuple[str, ...]) -> list[list[float]]:
    """Per-hop searoute polylines for a path's hops (cosmetic geometry, REQ-14-4).

    Each hop carries the [lon,lat] polyline of an ADJACENT leg so EVERY hop
    (including the origin hop 0) has a non-empty ``waypoints`` list: hop ``i>=1``
    gets the leg arriving at it (port[i-1]->port[i]); hop 0 gets the leg departing
    it (port[0]->port[1]). A single-hop path gets a degenerate point. Coords come
    pre-rounded/normalized from ``searoute_geometry.polyline_for`` — the analytic
    weights are untouched (geometry is cosmetic).
    """
    from lib.searoute_geometry import centroid_for, polyline_for

    codes = [_bare_code(str(r.get("port"))) for r in rows]
    per_hop: list[list[list[float]]] = []
    for i in range(len(codes)):
        if len(codes) == 1:
            per_hop.append([centroid_for(codes[0])])
            continue
        a, b = (codes[i - 1], codes[i]) if i >= 1 else (codes[0], codes[1])
        per_hop.append(polyline_for(centroid_for(a), centroid_for(b), restrict=restrict))
    return per_hop


def _path_legs(rows: list[Any], restrict: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Coerce path rows to plain dicts and attach per-hop ``waypoints`` (REQ-14-4)."""
    waypoints = _waypoints_for_path(rows, restrict) if rows else []
    legs: list[dict[str, Any]] = []
    for idx, r in enumerate(rows):
        leg: dict[str, Any] = {}
        for k, v in r.items():
            if isinstance(v, float):
                leg[k] = round(float(v), 12)
            elif isinstance(v, (int, str)) or v is None:
                leg[k] = v
            else:
                leg[k] = str(v)
        leg["waypoints"] = waypoints[idx]
        legs.append(leg)
    return legs


def _build_uc4_scenario(spec: dict[str, Any], db: Any = None) -> dict[str, Any]:
    """Build one curated UC4 scenario dict (baseline vs reroute + baked geometry).

    Derives the disabled lane set from the scenario's CLOSED chokepoint via the
    Plan-03 XOR rule (distinct per canal), runs baseline/reroute SHORTEST_PATH, and
    attaches per-leg ``waypoints``. The reroute ``delta`` stays on the haversine/18kn
    MODEL weights (``leg_hours``) — searoute distances are NEVER adopted.

    A ``fragmenting`` scenario (GIBRALTAR, PROJECT D-12) has NO model reroute — closing
    it disconnects the route. Such a scenario carries an empty ``reroute_path``,
    ``delta == 0``, ``reroute_available == False``, but keeps the COSMETIC Cape-of-Good-
    Hope baseline polyline so the map still has geometry to draw. Non-fragmenting
    scenarios (SUEZ/PANAMA) reroute around the closure with a strict ``delta > 0``.
    """
    from data_gen.network import LANES, US_US_LANES
    from lib.graph_loader import chokepoints_for_lane

    origin_id = _port_id(spec["origin"])
    dest_id = _port_id(spec["dest"])
    restrict = tuple(p for p in spec["restrict"].split(",") if p)
    fragmenting = bool(spec.get("fragmenting", False))
    disabled = disabled_lane_keys_for_chokepoint(
        tuple(LANES) + tuple(US_US_LANES), chokepoints_for_lane, spec["closed"]
    )

    baseline_rows = uc4_reroute.run_path(origin_id, dest_id, db=db)
    baseline_legs = uc4_reroute.leg_hours(baseline_rows)

    if fragmenting:
        # No model reroute exists — Gibraltar disconnects Europe (D-12). Report
        # fragmentation, not a fabricated detour: empty reroute, delta 0. The
        # cosmetic Cape baseline geometry still ships for the map.
        reroute_rows: list[Any] = []
        reroute_legs: list[float] = []
        delta = 0.0
        reroute_available = False
    else:
        reroute_rows = uc4_reroute.run_path(
            origin_id, dest_id, disabled_lanes=disabled, db=db
        )
        reroute_legs = uc4_reroute.leg_hours(reroute_rows)
        delta = float(reroute_delta(baseline_legs, reroute_legs))
        reroute_available = bool(reroute_rows)

    return {
        "id": str(spec["id"]),
        "label": str(spec["label"]),
        "closed": str(spec["closed"]),
        "origin": origin_id,
        "dest": dest_id,
        "fragmenting": fragmenting,
        "reroute_available": reroute_available,
        "disabled_lanes": [str(x) for x in disabled],
        "baseline_path": _path_legs(baseline_rows, restrict),
        "reroute_path": _path_legs(reroute_rows, restrict),
        "baseline_hours": round(float(sum(baseline_legs)), 12),
        "reroute_hours": round(float(sum(reroute_legs)), 12),
        "delta": round(float(delta), 12),
    }


def snapshot_uc4(db: Any = None) -> dict[str, Any]:
    """Assemble the credential-free UC4 reroute snapshot dict (curated scenarios[]).

    Builds a curated ``scenarios`` list (REQ-14-6) — at least Suez/Panama/Gibraltar,
    each closing a NAMED chokepoint (REQ-14-5) with per-leg baked sea-route
    ``waypoints`` (REQ-14-4) and a distinct disabled-lane set (Plan-03 XOR rule). The
    legacy top-level ``baseline_path``/``reroute_path``/``delta``/etc. MIRROR
    ``scenarios[0]`` verbatim so ``uc4-summary.tsx`` + ``test_uc4_reroute.py`` stay
    unchanged (Assumption A4). Deltas stay on the haversine/18kn MODEL weights; geometry
    is cosmetic. Returns ONLY counts / floats / strings / lists — no credential object.
    """
    scenarios = [_build_uc4_scenario(spec, db=db) for spec in _UC4_SCENARIOS]
    first = scenarios[0]
    return {
        "use_case": "UC4",
        # Legacy top-level mirror of scenarios[0] (A4 — unchanged downstream contract).
        "origin": first["origin"],
        "dest": first["dest"],
        "disabled_lanes": list(first["disabled_lanes"]),
        "baseline_path": first["baseline_path"],
        "reroute_path": first["reroute_path"],
        "baseline_hours": first["baseline_hours"],
        "reroute_hours": first["reroute_hours"],
        "delta": first["delta"],
        # REQ-14-6 curated scenarios with named closed chokepoint + baked geometry.
        "scenarios": scenarios,
    }


__all__ = ["snapshot_uc3", "snapshot_uc4"]
