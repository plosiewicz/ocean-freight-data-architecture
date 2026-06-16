"""Versioned-AQL loader/runner for the UC3/UC4 network queries.

This is the Python side of GRAPH-02 (UC3 chokepoint exposure + reversible
closure) and GRAPH-03 (UC4 weighted-`SHORTEST_PATH` rerouting). It mirrors the
supply-chain repo's ``aql/*.aql`` + ``aql/*.explain.txt`` discipline: the query
*bodies* live in versioned ``aql/uc*.aql`` files (so they are reviewable,
diff-able, and re-runnable verbatim), and this module only **loads and executes**
them — it never rebuilds a query by string concatenation.

Security (threat T-06-06 / ASVS V5): every UC parameter
(``@origin`` / ``@dest`` / ``@closed`` / ``@disabled_lanes`` / ``@maxhops``) is
passed as an AQL **bind variable** to ``db.aql.execute`` — user values are NEVER
f-stringed into the query text. The only string the runner sees is the immutable
on-disk ``.aql`` file.

Connection (threat T-06-01): the cluster is reached ONLY via
``lib.arango_client.get_db`` (env-driven, TLS-on); no credentials are logged.

Live execution of these queries against the managed cluster is gated to 06-05;
the offline UC tests (``tests/test_uc3_closure.py`` / ``tests/test_uc4_reroute.py``)
exercise the pure helpers (closure filter, reachability count, reroute delta)
and the AQL string contracts without a cluster.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Repo-root /aql directory (lib/ is a direct child of the git root).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_AQL_DIR = _REPO_ROOT / "aql"

# The versioned UC queries this module is allowed to load (an allow-list keeps a
# caller from reading an arbitrary file off disk via a crafted ``name``).
_KNOWN_QUERIES = (
    "uc3_chokepoint_share",
    "uc3_closure_unreachable",
    "uc3_reroute_impact",
    "uc4_reroute_shortest_path",
)


def load_aql(name: str) -> str:
    """Read a versioned ``aql/<name>.aql`` query body and return it as text.

    ``name`` is the bare query stem (``"uc4_reroute_shortest_path"``), with or
    without a trailing ``.aql``. Only the known UC queries are loadable — an
    unknown name raises :class:`ValueError` (no path traversal / arbitrary read).
    """
    stem = name[:-4] if name.endswith(".aql") else name
    if stem not in _KNOWN_QUERIES:
        raise ValueError(
            f"unknown AQL query {name!r}; expected one of {_KNOWN_QUERIES}"
        )
    path = _AQL_DIR / f"{stem}.aql"
    if not path.is_file():
        raise FileNotFoundError(f"versioned AQL file missing: {path}")
    return path.read_text()


def run_query(
    name: str,
    bind_vars: Mapping[str, Any] | None = None,
    *,
    db: Any = None,
    request_timeout: float | None = None,
) -> list[Any]:
    """Execute a versioned UC query with bind variables and return all rows.

    The query text is loaded verbatim from ``aql/<name>.aql`` and run through
    ``db.aql.execute(query, bind_vars=...)`` — every UC parameter is a bind
    variable, never interpolated (threat T-06-06). If ``db`` is not supplied the
    connection is opened lazily via :func:`lib.arango_client.get_db` (TLS-on,
    env-driven). Live execution is exercised in 06-05; the offline tests use the
    pure helpers below instead.
    """
    query = load_aql(name)
    if db is None:
        from lib.arango_client import get_db  # lazy: no cluster import at module load

        db = get_db(request_timeout=request_timeout)
    cursor = db.aql.execute(query, bind_vars=dict(bind_vars or {}))
    return list(cursor)


def closed_lane_keys(
    transits: Mapping[str, str], chokepoint: str
) -> list[str]:
    """Return the lane ``_key``s whose ``transits_chokepoint`` hits ``chokepoint``.

    Pure mirror of the AQL ``closed_lanes`` LET in
    ``aql/uc3_closure_unreachable.aql`` over a ``{lane_key: chokepoint_key}`` map.
    Closing a chokepoint EXCLUDES exactly these lanes (a reversible FILTER — the
    map is never mutated, D-09 / threat T-06-07).
    """
    return [lane for lane, choke in transits.items() if choke == chokepoint]


def disabled_lane_keys_for_chokepoint(
    lanes: Iterable[tuple[str, str]],
    rule,
    chokepoint: str,
) -> list[str]:
    """Resolve a closed ``chokepoint`` to the route-edge ``lane_key``s transiting it.

    The pure mirror of the live UC3-reroute-impact / closure binding: over the
    canonical directed port-pair network (``data_gen.network.LANES`` /
    ``US_US_LANES``) and the deterministic geographic ``rule``
    (``lib.graph_loader.chokepoints_for_lane``), a lane transits ``chokepoint`` iff
    ``chokepoint`` is in its rule result. The returned ``f"{origin}__{dest}"`` keys
    are exactly the values written as the route edge ``lane_key`` attribute (the
    shared bridge), so the offline ``@disabled_lanes`` set mirrors the live one
    (D-09 / D-12). Order-stable (follows ``lanes`` order).
    """
    return [
        f"{origin}__{dest}"
        for (origin, dest) in lanes
        if chokepoint in rule(origin, dest)
    ]


def reachable_lane_count(
    all_lanes: Iterable[str], *, closed: Iterable[str]
) -> int:
    """Count lanes still reachable once ``closed`` lanes are filtered out.

    The offline analogue of the per-origin reachability traversal: a lane is
    reachable iff it is not in the closed set. Pure (no graph mutation), so
    baseline (``closed=[]``) and post-closure counts can be compared back-to-back.
    """
    closed_set = set(closed)
    return sum(1 for lane in all_lanes if lane not in closed_set)


def reroute_delta(
    baseline_legs: Sequence[float], reroute_legs: Sequence[float]
) -> float:
    """Reroute delta = SUM(reroute leg_hours) - SUM(baseline leg_hours) (D-10).

    A positive delta is the extra ``transit_time_hours`` the disruption forces;
    each leg list is the ``leg_hours`` column returned by
    ``aql/uc4_reroute_shortest_path.aql`` (baseline run vs. ``@disabled_lanes``
    run).
    """
    return float(sum(reroute_legs)) - float(sum(baseline_legs))


def explain(
    name: str,
    bind_vars: Mapping[str, Any] | None = None,
    *,
    db: Any = None,
) -> str:
    """Return the EXPLAIN plan JSON for a UC query (the index-not-fullscan defense).

    Mirrors ``supply-chain/aql/uc4_rebalance.explain.txt``: the plan is captured
    alongside the ``.aql`` file as evidence the traversal/SHORTEST_PATH is
    index-backed rather than a full scan. The plan is generated against the live
    cluster (06-05); this is the runner hook. Bind variables are still passed as
    binds — the EXPLAIN path is not a string-interpolation back door.
    """
    query = load_aql(name)
    if db is None:
        from lib.arango_client import get_db

        db = get_db()
    plan = db.aql.explain(query, bind_vars=dict(bind_vars or {}))
    return json.dumps(plan, indent=2, sort_keys=True, default=str)
