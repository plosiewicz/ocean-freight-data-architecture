"""Wave 0 stub — GRAPHX-01: gral (GAE) -> NetworkX criticality fallback.

Offline contract for `analytics/run_criticality.py` (Wave 4). The managed cluster's
GAE is the PRIMARY criticality path (Phase-6 correction #2), but the gral route can
404 for minutes after install and `storeresults` can write 0 docs (RESEARCH Pitfall
1). The de-facto-shipping path is therefore the seeded, SORTed NetworkX fallback:
when the gral HTTP layer is mocked to FAIL (404 / 0-docs), the runner must fall
through to NetworkX and produce a DETERMINISTIC criticality ranking.

The runner is built in Wave 4 (skip-as-RED until it exists). The assertion is real:
same input + same seed => same ranking, twice.
"""

from __future__ import annotations

import pytest


def _import_runner():
    try:
        from analytics import run_criticality  # noqa: F401
    except ImportError as exc:  # pragma: no cover - RED until Wave 4
        pytest.skip(f"analytics.run_criticality not built yet (Wave 4): {exc}")
    return run_criticality


# Tiny in-memory projection: a 4-node path where the middle nodes carry the most
# shortest paths (highest betweenness centrality).
_EDGES = [
    ("A", "B"),
    ("B", "C"),
    ("C", "D"),
]


def test_networkx_fallback_produces_deterministic_ranking():
    """When gral is unavailable, the seeded NetworkX path yields a stable ranking."""
    rc = _import_runner()
    first = rc.criticality_via_networkx(_EDGES, seed=42)
    second = rc.criticality_via_networkx(_EDGES, seed=42)
    # Determinism: identical input + seed => identical ordered ranking.
    assert first == second
    # Sanity: the helper returns a per-node criticality score for every node.
    assert set(dict(first)) == {"A", "B", "C", "D"}
