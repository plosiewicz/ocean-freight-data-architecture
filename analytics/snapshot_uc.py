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
    baseline_rows = uc3_closure.run_closure(OPEN_SENTINEL, db=db)
    gib_rows = uc3_closure.run_closure(FRAGMENTING_CHOKEPOINT, db=db)
    closure_gibraltar = {
        "closed": FRAGMENTING_CHOKEPOINT,
        "open_reachable_total": _total_reachable(baseline_rows),
        "closed_reachable_total": _total_reachable(gib_rows),
        "open_origins": int(len(baseline_rows)),
        "closed_origins": int(len(gib_rows)),
    }

    return {
        "use_case": "UC3",
        "origin": DEMO_ORIGIN,
        "dest": DEMO_DEST,
        "transit_share": transit_share,
        "reroute_impact_suez": reroute_impact_suez,
        "closure_gibraltar": closure_gibraltar,
    }


def snapshot_uc4(db: Any = None) -> dict[str, Any]:
    """Assemble the credential-free UC4 reroute snapshot dict (baseline vs reroute path).

    Delegates to ``analytics.uc4_reroute.run_path`` (bind vars only): the baseline
    USNYC->CNSHA weighted SHORTEST_PATH, then the reroute with the SUEZ-transiting
    lanes disabled, plus :func:`reroute_delta`. Returns ONLY counts / floats /
    strings / lists — no client or credential object.
    """
    from data_gen.network import LANES, US_US_LANES
    from lib.graph_loader import chokepoints_for_lane

    origin_id = DEMO_ORIGIN if "/" in DEMO_ORIGIN else f"ports/{DEMO_ORIGIN}"
    dest_id = DEMO_DEST if "/" in DEMO_DEST else f"ports/{DEMO_DEST}"
    disabled = disabled_lane_keys_for_chokepoint(
        tuple(LANES) + tuple(US_US_LANES),
        chokepoints_for_lane,
        REROUTE_IMPACT_CHOKEPOINT,
    )

    baseline_rows = uc4_reroute.run_path(origin_id, dest_id, db=db)
    reroute_rows = uc4_reroute.run_path(origin_id, dest_id, disabled_lanes=disabled, db=db)
    baseline_legs = uc4_reroute.leg_hours(baseline_rows)
    reroute_legs = uc4_reroute.leg_hours(reroute_rows)

    def _path_legs(rows: list[Any]) -> list[dict[str, Any]]:
        legs: list[dict[str, Any]] = []
        for r in rows:
            leg: dict[str, Any] = {}
            for k, v in r.items():
                if isinstance(v, float):
                    leg[k] = round(float(v), 12)
                elif isinstance(v, (int, str)) or v is None:
                    leg[k] = v
                else:
                    leg[k] = str(v)
            legs.append(leg)
        return legs

    return {
        "use_case": "UC4",
        "origin": origin_id,
        "dest": dest_id,
        "disabled_lanes": [str(x) for x in disabled],
        "baseline_path": _path_legs(baseline_rows),
        "reroute_path": _path_legs(reroute_rows),
        "baseline_hours": round(float(sum(baseline_legs)), 12),
        "reroute_hours": round(float(sum(reroute_legs)), 12),
        "delta": round(float(reroute_delta(baseline_legs, reroute_legs)), 12),
    }


__all__ = ["snapshot_uc3", "snapshot_uc4"]
