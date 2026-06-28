"""14-04 — offline golden-SHAPE contract for the enriched UC3/UC4 snapshot.

Credential-free, no-cluster unit test. Pins the shapes the map render layer
(Plan 05) and the live re-freeze (Plan 06) depend on, AFTER the geometry
enrichment of ``analytics/snapshot_uc.py``:

  UC4 (snapshot_uc4):
    * a ``scenarios`` list of length >= 3 (Suez / Panama / Gibraltar curated);
    * each scenario carries ``id``, ``label``, ``closed`` (SUEZ/PANAMA/GIBRALTAR),
      ``origin``, ``dest``, ``baseline_path``, ``reroute_path``, ``delta``;
    * every hop of every path carries a NON-EMPTY ``waypoints`` list of [lon,lat];
    * the Suez scenario and the Panama scenario have DISTINCT reroute geometry;
    * the legacy top-level ``baseline_path``/``reroute_path``/``delta`` MIRROR
      ``scenarios[0]`` verbatim (Assumption A4 — uc4-summary.tsx unchanged);
    * EVERY curated scenario has reroute ``delta`` > 0 (offline non-degeneracy —
      a degenerate curated scenario is caught HERE in Wave 2, not at Plan-06 freeze);
    * deltas stay on the haversine/18kn MODEL weights, never searoute distances.

  UC3 (snapshot_uc3):
    * each ``closure_by_chokepoint`` entry carries a ``disabled_lanes`` list of
      ``A__B`` lane-key strings (not just the count);
    * each entry carries ``disabled_lane_paths``: a list of
      ``{lane_key, waypoints:[[lon,lat]...]}``;
    * SUEZ and PANAMA entries carry DIFFERENT ``disabled_lanes`` key sets (XOR rule);
    * existing ``disabled_lane_count`` and all prior keys remain unchanged (additive).

  Freezer (scripts/freeze_uc.py) direction-only NON-DEGENERACY contract:
    * ``freeze_uc`` exits EMPTY when UC4 ``scenarios`` is empty;
    * it exits EMPTY when any curated scenario's reroute ``delta`` <= 0;
    * the freezer SOURCE pins NO hard-coded magnitude (no literal ``76.22``, no
      ``== 12`` magnitude comparison) — direction-only contract (Pitfall 4).

All assertions are DIRECTION / SHAPE only (no coordinate or hour magnitudes) and
run against in-memory MOCKED runners — no cluster, no credentials. Mirrors the
offline import-or-skip-RED idiom from ``tests/test_arango_load.py``.
"""

from __future__ import annotations

import pathlib

import pytest

# ---- in-memory route network mirroring the real topology (no cluster) -------
# leg rows are the {port, leg_hours} shape that aql/uc4_reroute_shortest_path.aql
# emits; hours are the haversine/18kn-style MODEL weights (NOT searoute distances).
_FIXTURE_ROUTES: dict[str, dict] = {
    # Asia <-> US-East, Suez-routed (USNYC) — closing SUEZ forces the Pacific detour.
    "USNYC__CNSHA": {"hours": 356.0, "ports": ["USNYC", "CNSHA"]},
    "USNYC__USLAX": {"hours": 120.0, "ports": ["USNYC", "USLAX"]},
    "USLAX__CNSHA": {"hours": 312.0, "ports": ["USLAX", "CNSHA"]},
    # Europe <-> US-West, Panama-routed (USLAX-Gulf) — closing PANAMA forces a detour.
    "DEHAM__USLAX": {"hours": 290.0, "ports": ["DEHAM", "USLAX"]},
    "DEHAM__USNYC": {"hours": 180.0, "ports": ["DEHAM", "USNYC"]},
    # Europe <-> US-East, Gibraltar-routed — closing GIBRALTAR forces a detour.
    "USNYC__DEHAM": {"hours": 180.0, "ports": ["USNYC", "DEHAM"]},
}


def _shortest(origin: str, dest: str, disabled: set[str]) -> list[dict]:
    """Tiny Dijkstra over the fixture; returns {port, leg_hours} rows (AQL shape)."""
    import heapq

    o = origin.split("/", 1)[-1]
    d = dest.split("/", 1)[-1]
    adj: dict[str, list[tuple[str, float, str]]] = {}
    for lk, e in _FIXTURE_ROUTES.items():
        if lk in disabled:
            continue
        a, b = lk.split("__", 1)
        adj.setdefault(a, []).append((b, e["hours"], lk))
        adj.setdefault(b, []).append((a, e["hours"], lk))  # undirected for the fixture
    pq = [(0.0, o, [o], [0.0])]
    seen: set[str] = set()
    while pq:
        cost, node, path, legs = heapq.heappop(pq)
        if node == d:
            return [{"port": p, "leg_hours": legs[i]} for i, p in enumerate(path)]
        if node in seen:
            continue
        seen.add(node)
        for nxt, w, _lk in adj.get(node, []):
            if nxt not in seen:
                heapq.heappush(pq, (cost + w, nxt, path + [nxt], legs + [w]))
    return []


def _import():
    try:
        from analytics import snapshot_uc  # noqa: F401
    except ImportError as exc:  # pragma: no cover - RED until Task 1
        pytest.skip(f"analytics.snapshot_uc not built yet: {exc}")
    return snapshot_uc


@pytest.fixture
def patched_uc4(monkeypatch):
    """Patch uc4_reroute.run_path with the in-memory fixture (no cluster)."""
    from analytics import uc4_reroute

    def fake_run_path(origin, dest, *, disabled_lanes=None, db=None):
        return _shortest(origin, dest, set(disabled_lanes or []))

    monkeypatch.setattr(uc4_reroute, "run_path", fake_run_path)
    return fake_run_path


@pytest.fixture
def patched_uc3(monkeypatch):
    """Patch uc3_closure runners with in-memory fixtures (no cluster)."""
    from analytics import uc3_closure
    from lib.graph_loader import chokepoints_for_lane

    # transit_share: one row per chokepoint that any fixture lane transits.
    def fake_transit_share(*, db=None):
        cps: dict[str, int] = {}
        for lk in _FIXTURE_ROUTES:
            o, d = lk.split("__", 1)
            for cp in chokepoints_for_lane(o, d):
                cps[cp] = cps.get(cp, 0) + 1
        return [
            {"chokepoint": cp, "transiting_lanes": n, "total_lanes": len(_FIXTURE_ROUTES),
             "transit_share_pct": n / len(_FIXTURE_ROUTES)}
            for cp, n in cps.items()
        ]

    def fake_run_closure(closed, *, maxhops=200, db=None):
        # one reachable-count row per US origin; closing a real chokepoint drops one.
        base = 29
        drop = 18 if closed == "GIBRALTAR" else 0
        return [{"origin": "USNYC", "reachable_count": base - drop}]

    def fake_run_reroute_impact(closed, origin, dest, *, db=None):
        from lib.graph_queries import disabled_lane_keys_for_chokepoint, reroute_delta
        lane_pairs = tuple(tuple(lk.split("__", 1)) for lk in _FIXTURE_ROUTES)
        disabled = disabled_lane_keys_for_chokepoint(
            lane_pairs, chokepoints_for_lane, closed
        )
        oid = origin if "/" in origin else f"ports/{origin}"
        did = dest if "/" in dest else f"ports/{dest}"
        baseline = [r["leg_hours"] for r in _shortest(oid, did, set())]
        reroute = [r["leg_hours"] for r in _shortest(oid, did, set(disabled))]
        return {
            "closed": closed, "origin": oid, "dest": did,
            "disabled_lanes": disabled, "baseline_legs": baseline,
            "reroute_legs": reroute, "delta": reroute_delta(baseline, reroute),
        }

    monkeypatch.setattr(uc3_closure, "run_transit_share", fake_transit_share)
    monkeypatch.setattr(uc3_closure, "run_closure", fake_run_closure)
    monkeypatch.setattr(uc3_closure, "run_reroute_impact", fake_run_reroute_impact)


# ----------------------------- UC4 scenarios --------------------------------- #
def test_uc4_scenarios_is_list_len_ge_3(patched_uc4):
    sg = _import()
    body = sg.snapshot_uc4()
    assert isinstance(body["scenarios"], list)
    assert len(body["scenarios"]) >= 3


def test_uc4_each_scenario_has_required_keys(patched_uc4):
    sg = _import()
    body = sg.snapshot_uc4()
    closed_seen = set()
    for sc in body["scenarios"]:
        for k in ("id", "label", "closed", "origin", "dest",
                  "baseline_path", "reroute_path", "delta"):
            assert k in sc, f"scenario missing {k}"
        assert sc["closed"] in ("SUEZ", "PANAMA", "GIBRALTAR")
        closed_seen.add(sc["closed"])
    assert {"SUEZ", "PANAMA", "GIBRALTAR"} <= closed_seen


def test_uc4_every_hop_carries_nonempty_waypoints(patched_uc4):
    sg = _import()
    body = sg.snapshot_uc4()
    for sc in body["scenarios"]:
        for path_key in ("baseline_path", "reroute_path"):
            assert sc[path_key], f"{path_key} empty"
            for hop in sc[path_key]:
                wp = hop.get("waypoints")
                assert isinstance(wp, list) and len(wp) > 0
                for pt in wp:
                    assert isinstance(pt, list) and len(pt) == 2


def test_uc4_suez_and_panama_reroute_geometry_distinct(patched_uc4):
    sg = _import()
    scenarios = {sc["closed"]: sc for sc in sg.snapshot_uc4()["scenarios"]}

    def all_waypoints(sc):
        return [hop["waypoints"] for hop in sc["reroute_path"]]

    assert all_waypoints(scenarios["SUEZ"]) != all_waypoints(scenarios["PANAMA"])


def test_uc4_legacy_top_level_mirrors_scenario_zero(patched_uc4):
    sg = _import()
    body = sg.snapshot_uc4()
    s0 = body["scenarios"][0]
    assert body["baseline_path"] == s0["baseline_path"]
    assert body["reroute_path"] == s0["reroute_path"]
    assert body["delta"] == s0["delta"]


def test_uc4_every_scenario_delta_strictly_positive(patched_uc4):
    """Offline non-degeneracy: EACH curated scenario reroutes (delta > 0)."""
    sg = _import()
    for sc in sg.snapshot_uc4()["scenarios"]:
        assert sc["delta"] > 0, f"{sc['closed']} scenario is degenerate (delta<=0)"


def test_uc4_delta_uses_model_weights_not_searoute(patched_uc4):
    """delta comes from the fixture (model) leg_hours, not searoute distances."""
    sg = sg = _import()
    s0 = [s for s in sg.snapshot_uc4()["scenarios"] if s["closed"] == "SUEZ"][0]
    # SUEZ on USNYC->CNSHA: baseline 356, reroute 120+312=432, delta 76 (model).
    assert s0["delta"] == pytest.approx(76.0)


# ----------------------------- UC3 disabled lanes ---------------------------- #
def test_uc3_entries_carry_disabled_lane_keys(patched_uc3):
    sg = _import()
    entries = sg.snapshot_uc3()["closure_by_chokepoint"]
    for e in entries:
        assert isinstance(e["disabled_lanes"], list)
        for k in e["disabled_lanes"]:
            assert isinstance(k, str) and "__" in k


def test_uc3_entries_carry_disabled_lane_paths(patched_uc3):
    sg = _import()
    entries = sg.snapshot_uc3()["closure_by_chokepoint"]
    for e in entries:
        assert isinstance(e["disabled_lane_paths"], list)
        for p in e["disabled_lane_paths"]:
            assert "lane_key" in p and "waypoints" in p
            assert isinstance(p["waypoints"], list)
            if p["waypoints"]:
                assert all(isinstance(pt, list) and len(pt) == 2 for pt in p["waypoints"])


def test_uc3_suez_panama_disabled_sets_distinct(patched_uc3):
    sg = _import()
    by_cp = {e["chokepoint"]: e for e in sg.snapshot_uc3()["closure_by_chokepoint"]}
    suez = set(by_cp["SUEZ"]["disabled_lanes"])
    panama = set(by_cp["PANAMA"]["disabled_lanes"])
    assert suez != panama
    assert suez and panama


def test_uc3_existing_keys_preserved(patched_uc3):
    sg = _import()
    entries = sg.snapshot_uc3()["closure_by_chokepoint"]
    for e in entries:
        for k in ("chokepoint", "open_reachable_total", "closed_reachable_total",
                  "reroute_delta_hours", "disabled_lane_count"):
            assert k in e
        # disabled_lane_count stays the LENGTH of disabled_lanes (additive, unchanged).
        assert e["disabled_lane_count"] == len(e["disabled_lanes"])


# ----------------------------- freezer contract ------------------------------ #
def _freeze_uc():
    try:
        import scripts.freeze_uc as fz  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"scripts.freeze_uc not importable: {exc}")
    return fz


def test_freezer_exits_empty_on_missing_scenarios(patched_uc4, monkeypatch):
    fz = _freeze_uc()
    from analytics import snapshot_uc

    def empty_scenarios(db=None):
        body = snapshot_uc.snapshot_uc4.__wrapped__(db) if hasattr(
            snapshot_uc.snapshot_uc4, "__wrapped__") else None
        return {"use_case": "UC4", "scenarios": []}

    monkeypatch.setattr("analytics.snapshot_uc.snapshot_uc4", empty_scenarios)
    code, body = fz._freeze_uc4()
    assert code == fz.EXIT_EMPTY


def test_freezer_exits_empty_on_degenerate_scenario(patched_uc4, monkeypatch):
    fz = _freeze_uc()

    def degenerate(db=None):
        return {
            "use_case": "UC4",
            "baseline_path": [{"port": "USNYC", "waypoints": [[0.0, 0.0]]}],
            "reroute_path": [{"port": "USNYC", "waypoints": [[0.0, 0.0]]}],
            "delta": 76.0,
            "scenarios": [
                {"id": "s1", "label": "L", "closed": "SUEZ", "origin": "ports/USNYC",
                 "dest": "ports/CNSHA",
                 "baseline_path": [{"port": "USNYC", "waypoints": [[0.0, 0.0]]}],
                 "reroute_path": [{"port": "USNYC", "waypoints": [[0.0, 0.0]]}],
                 "delta": 0.0},  # degenerate
            ],
        }

    monkeypatch.setattr("analytics.snapshot_uc.snapshot_uc4", degenerate)
    code, body = fz._freeze_uc4()
    assert code == fz.EXIT_EMPTY


def test_freezer_source_has_no_hardcoded_magnitude():
    """Direction-only contract: no literal 76.22 / no '== 12' magnitude pin (Pitfall 4)."""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "scripts" / "freeze_uc.py").read_text()
    assert "76.22" not in src
    assert "== 12" not in src
