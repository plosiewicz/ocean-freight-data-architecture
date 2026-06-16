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
