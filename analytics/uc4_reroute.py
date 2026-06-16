"""UC4 (GRAPH-03) — weighted-SHORTEST_PATH reroute, Python API.

Thin use-case facade over ``lib.graph_queries``: the reroute-delta math
(``delta = SUM(reroute leg_hours) - SUM(baseline leg_hours)``, D-10) is the pure
helper ``tests/test_uc4_reroute.py`` pins, and the weighted-path query
(``aql/uc4_reroute_shortest_path.aql``) is loaded/run through this module in
06-05.

The path is weighted by ``transit_time_hours`` — the SAME signal the warehouse
uses for UC1 reliability (D-08 coherence). All UC params are AQL bind variables;
no user value is string-interpolated (threat T-06-06). SHORTEST_PATH does not
support negative weights — durations are non-negative.
"""

from __future__ import annotations

from typing import Any, Sequence

from lib.graph_queries import reroute_delta as reroute_delta, run_query

REROUTE_QUERY = "uc4_reroute_shortest_path"


def run_path(
    origin: str,
    dest: str,
    *,
    disabled_lanes: Sequence[str] | None = None,
    db: Any = None,
) -> list[Any]:
    """Run the weighted SHORTEST_PATH (bind vars only).

    ``disabled_lanes=None`` (or ``[]``) is the baseline path; passing the lanes
    transiting a closed chokepoint yields the reroute path. The two leg-hour
    lists feed :func:`reroute_delta`.
    """
    return run_query(
        REROUTE_QUERY,
        {
            "origin": origin,
            "dest": dest,
            "disabled_lanes": list(disabled_lanes or []),
        },
        db=db,
    )


def leg_hours(rows: Sequence[dict[str, Any]]) -> list[float]:
    """Extract the per-leg ``leg_hours`` column from a reroute-query result."""
    return [float(r.get("leg_hours", 0) or 0) for r in rows]


__all__ = ["reroute_delta", "run_path", "leg_hours", "REROUTE_QUERY"]
