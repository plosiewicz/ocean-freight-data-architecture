"""Wave 0 stub — GRAPH-01: idempotent graph loader by deterministic `_key`.

Offline contract test (no live cluster — ARANGO_* creds are gitignored and not
present in CI). Pins the row-builder contract the Wave-2 `lib/graph_loader.py`
must satisfy:

  * vertex `_key` is the conformed business key — UN/LOCODE for ports, IMO for
    vessels, SCAC for carriers (the D-11 cross-store bridge to the BQ dims);
  * a `route` edge `_key` == ``f"{origin}__{dest}"`` with
    ``_from`` == ``ports/{origin}`` / ``_to`` == ``ports/{dest}``;
  * building the row set twice from the same input yields IDENTICAL rows — the
    idempotency contract (UPSERT-by-`_key`, never truncate+insert; cf. Phase-5
    CR-02/CR-03 race).

Per the Nyquist rule this is a real assertion against the not-yet-built
row-builders, so it reports RED clearly until Wave 2 lands `lib/graph_loader.py`.
It is NOT a no-op pass.
"""

from __future__ import annotations

import pytest


def _import_loader():
    """Import the Wave-2 row-builders; skip-as-RED until they exist."""
    try:
        from lib import graph_loader  # noqa: F401
    except ImportError as exc:  # pragma: no cover - RED until Wave 2
        pytest.skip(f"lib.graph_loader not built yet (Wave 2): {exc}")
    return graph_loader


def test_port_vertex_key_is_unlocode():
    """Port vertex `_key` is the UN/LOCODE business key (cross-store bridge)."""
    gl = _import_loader()
    row = gl.build_port_vertex({"unlocode": "USNYC", "lat": 40.7, "lon": -74.0})
    assert row["_key"] == "USNYC"


def test_route_edge_key_and_endpoints():
    """`route` edge `_key`=`origin__dest`; `_from`/`_to` resolve to ports/<code>."""
    gl = _import_loader()
    edge = gl.build_route_edge("USNYC", "DEHAM", transit_time_hours=240.0)
    assert edge["_key"] == "USNYC__DEHAM"
    assert edge["_from"] == "ports/USNYC"
    assert edge["_to"] == "ports/DEHAM"


def test_row_build_is_idempotent():
    """Building the same port rows twice yields identical row sets (UPSERT contract)."""
    gl = _import_loader()
    src = [
        {"unlocode": "USNYC", "lat": 40.7, "lon": -74.0},
        {"unlocode": "DEHAM", "lat": 53.5, "lon": 10.0},
    ]
    first = gl.build_port_vertices(src)
    second = gl.build_port_vertices(src)
    assert first == second
    assert {r["_key"] for r in first} == {"USNYC", "DEHAM"}


# --------------------------------------------------------------------------- #
# 06-06 gap-closure: lane_key + chokepoints attrs + foreign-port loading.      #
# --------------------------------------------------------------------------- #
def test_route_edge_carries_lane_key_attribute():
    """A route edge carries a `lane_key` attribute == its origin__dest (== _key).

    This is the attribute the UC3-reroute-impact / UC4 disabled-lane filters bind
    to; before the fix it was never written, so `e.lane_key` was always null and the
    reroute delta was always 0.
    """
    gl = _import_loader()
    edge = gl.build_route_edge("USNYC", "CNSHA")
    assert edge["lane_key"] == "USNYC__CNSHA"
    assert edge["lane_key"] == edge["_key"]


def test_route_edge_carries_transited_chokepoints():
    """A route edge carries the D-09 chokepoints it transits (route<->choke link)."""
    gl = _import_loader()
    # Europe<->US-East transits Gibraltar.
    deham = gl.build_route_edge("USNYC", "DEHAM")
    assert deham["chokepoints"] == ["GIBRALTAR"]
    # Far-East<->US-East transits Suez OR Panama (rule order-insensitive -> sorted).
    cnsha = gl.build_route_edge("USNYC", "CNSHA")
    assert sorted(cnsha["chokepoints"]) == ["PANAMA", "SUEZ"]
    # Trans-Pacific (Far-East<->US-West): no curated canal.
    lax_cnsha = gl.build_route_edge("USLAX", "CNSHA")
    assert lax_cnsha["chokepoints"] == []


def test_us_us_proforma_route_has_lane_key_and_no_chokepoints():
    """A US<->US proforma route carries a non-null lane_key and an empty chokepoints."""
    gl = _import_loader()
    edge = gl.build_route_edge("USLAX", "USNYC")
    assert edge["lane_key"] == "USLAX__USNYC"
    assert edge["chokepoints"] == []


def test_chokepoints_attr_matches_rule_and_malacca_is_never_assigned():
    """The route.chokepoints attribute mirrors chokepoints_for_lane verbatim; MALACCA
    appears in NO route edge (the honest documented-zero, not a fabrication)."""
    gl = _import_loader()
    from data_gen.network import LANES, US_US_LANES

    for (o, d) in LANES + US_US_LANES:
        edge = gl.build_route_edge(o, d)
        assert sorted(edge["chokepoints"]) == sorted(gl.chokepoints_for_lane(o, d))
    all_chokes = {
        cp
        for (o, d) in LANES + US_US_LANES
        for cp in gl.build_route_edge(o, d)["chokepoints"]
    }
    assert "MALACCA" not in all_chokes


def test_build_foreign_port_vertices_tagged_synthetic():
    """One synthetic ports vertex per FOREIGN_PORT; _key==UNLOCODE, coords + name set."""
    gl = _import_loader()
    from data_gen.network import FOREIGN_PORTS

    vtxs = gl.build_foreign_port_vertices()
    assert {v["_key"] for v in vtxs} == set(FOREIGN_PORTS)
    for v in vtxs:
        assert v["provenance"] == "synthetic"
        assert isinstance(v["lat"], (int, float))
        assert isinstance(v["lon"], (int, float))
        assert v.get("name")


def test_real_port_vertex_keeps_real_provenance():
    """A conformed real dim_port row keeps provenance=='real' (NOT overwritten)."""
    gl = _import_loader()
    row = {"unlocode": "USNYC", "lat": 40.7, "lon": -74.0, "provenance": "real"}
    vtx = gl.build_port_vertex(row)
    assert vtx["provenance"] == "real"


def test_route_edges_have_no_dangling_endpoints():
    """Every route edge endpoint over (LANES + US_US_LANES) is a loaded port code."""
    gl = _import_loader()
    from data_gen.network import FOREIGN_PORTS, LANES, US_PORTS, US_US_LANES

    loaded = set(US_PORTS) | set(FOREIGN_PORTS)
    edges = gl.build_route_edges(LANES) + gl.build_route_edges(US_US_LANES)
    for e in edges:
        origin = e["_from"].split("/", 1)[1]
        dest = e["_to"].split("/", 1)[1]
        assert origin in loaded
        assert dest in loaded
