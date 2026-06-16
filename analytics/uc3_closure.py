"""UC3 (GRAPH-02) — chokepoint closure filter + reachability, Python API.

Thin use-case facade over ``lib.graph_queries``: the closure FILTER (which lanes
drop when a chokepoint is closed) and the reachability count are the pure helpers
the offline test ``tests/test_uc3_closure.py`` pins, and the live closure query
(``aql/uc3_closure_unreachable.aql``) is loaded/run through this module in 06-05.

Closure is REVERSIBLE — it is a FILTER/NOT-IN exclusion, never a REMOVE/DELETE —
so Suez / Panama / Malacca scenarios run back-to-back without mutating shared
graph state (D-09 / threat T-06-07). All UC params are AQL bind variables
(threat T-06-06).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from lib.graph_queries import (
    closed_lane_keys as closed_lane_keys,
    reachable_lane_count as reachable_lane_count,
    run_query,
)

CLOSURE_QUERY = "uc3_closure_unreachable"
SHARE_QUERY = "uc3_chokepoint_share"

# Featured chokepoints for the demo narrative (D-09).
FEATURED_CHOKEPOINTS = ("SUEZ", "PANAMA", "MALACCA")


def run_transit_share(*, db: Any = None) -> list[Any]:
    """Run the transit-share query (no binds) and return per-chokepoint rows."""
    return run_query(SHARE_QUERY, {}, db=db)


def run_closure(closed: str, *, maxhops: int = 6, db: Any = None) -> list[Any]:
    """Run the reversible closure query for chokepoint ``closed`` (bind vars only)."""
    return run_query(
        CLOSURE_QUERY,
        {"closed": closed, "maxhops": maxhops},
        db=db,
    )


__all__ = [
    "closed_lane_keys",
    "reachable_lane_count",
    "run_transit_share",
    "run_closure",
    "CLOSURE_QUERY",
    "SHARE_QUERY",
    "FEATURED_CHOKEPOINTS",
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
