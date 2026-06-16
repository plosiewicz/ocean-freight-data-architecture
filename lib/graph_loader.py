"""GRAPH-01 — idempotent projection of conformed Silver dims + the synthetic
priors-conditioned lane network into the LOCKED M2 ``ocean_network`` named graph.

This is the load-side of the ETL-05 "one transform, two sinks" story: the SAME
conformed ``silver/`` dims that feed the BigQuery star schema are projected here
into the ArangoDB property graph. The conformed-key bridge (D-11) is the linchpin
— every vertex ``_key`` is identical to the corresponding BigQuery dimension
business key: ``_key`` = UN/LOCODE for ports, IMO for vessels, SCAC for carriers.
That key identity makes the cross-store join 1:1 and proves the two stores are one
architecture rather than two disconnected databases.

Idempotency (D-06, threat T-06-05): every write is an AQL ``UPSERT { _key } INSERT
... UPDATE ...`` keyed on the deterministic ``_key``. Wiping a collection then
re-inserting is the LOCKED anti-pattern (Phase-5 CR-02/CR-03 wipe-then-reload race
lesson) — a re-run must leave the graph byte-stable, never corrupt or duplicate it,
and is therefore forbidden in this module. ``rows`` and the
collection name are passed as AQL BIND variables (``@rows`` / ``@@collection``),
never f-string-interpolated (threat T-06-06 / ASVS V5).

Connection is ONLY via :mod:`lib.arango_client` (env creds, TLS always on); this
module prints only ``[INFO]``/``[OK]`` counts, never credentials (threat T-06-01).

The pure row-builders (``build_*``) are deterministic and SIDE-EFFECT-FREE so they
run fully OFFLINE (no cluster) — that is what ``tests/test_arango_load.py`` exercises.
The live UPSERT (``load_graph``) runs in 06-05. ``load_graph(bucket=...) -> dict``
is the single entrypoint callable from BOTH the DAG ``load_arango`` task and the
``make load-arango`` target (D-06a).

Provenance: 06-PATTERNS.md "lib/graph_loader.py — NEW, idempotent UPSERT";
06-RESEARCH.md Pattern 2/3 + Code Example 2 + Pitfall 4 (sparse real weights);
docs/deck/m2-arango-graph.md (LOCKED 5 vertex + 4 edge collections, four D-08
weights). Edge definitions are NOT re-decided here — they are copied forward.
"""

from __future__ import annotations

import datetime as _dt
import io
from typing import Any

from data_gen.network import (
    CARRIER_SCACS,
    LANES,
    PORT_COUNTRY,
    US_US_LANES,
)
from silver.haversine import haversine_nm

# Default Silver bucket (mirrors scripts/verify.py BRONZE_BUCKET — Bronze + Silver
# share one bucket; the Silver tier lives under the ``silver/`` prefix).
BUCKET: str = "data-architecture-msds683-bronze"

# LOCKED named graph (docs/deck/m2-arango-graph.md D-07).
GRAPH_NAME: str = "ocean_network"

# LOCKED collection names (M2 — 5 vertex, 4 edge).
VERTEX_COLLECTIONS: tuple[str, ...] = ("ports", "vessels", "carriers", "lanes", "chokepoints")
EDGE_COLLECTIONS: tuple[str, ...] = ("route", "calls_at", "operates", "transits_chokepoint")

# LOCKED edge definitions (docs/deck/m2-arango-graph.md — DO NOT re-decide).
EDGE_DEFINITIONS: list[dict[str, Any]] = [
    {"edge_collection": "route", "from_vertex_collections": ["ports"], "to_vertex_collections": ["ports"]},
    {"edge_collection": "calls_at", "from_vertex_collections": ["vessels"], "to_vertex_collections": ["ports"]},
    {"edge_collection": "operates", "from_vertex_collections": ["carriers"], "to_vertex_collections": ["vessels"]},
    {
        "edge_collection": "transits_chokepoint",
        "from_vertex_collections": ["lanes"],
        "to_vertex_collections": ["chokepoints"],
    },
]

# Vertex-centric persistent index on the chokepoint supernode edge (ROADMAP success
# criterion 2): keeps the chokepoint-share / closure traversal bounded by indexing
# the ``_to`` side of transits_chokepoint (the high-fan-in chokepoint endpoint).
VC_CHOKE_INDEX_NAME: str = "vc_choke_to"

# --------------------------------------------------------------------------- #
# Curated chokepoint set (D-09, docs/deck/m2-arango-graph.md "Chokepoint honesty").
# These are NOT observed from the US-coastal AIS slice — they are rule-assigned
# over the synthetic lane network by geography. `_key` is the chokepoint code.
# --------------------------------------------------------------------------- #
CHOKEPOINTS: tuple[dict[str, Any], ...] = (
    {"_key": "SUEZ", "name": "Suez Canal", "lat": 30.0, "lon": 32.35},
    {"_key": "PANAMA", "name": "Panama Canal", "lat": 9.08, "lon": -79.68},
    {"_key": "MALACCA", "name": "Strait of Malacca", "lat": 2.5, "lon": 101.5},
    {"_key": "GIBRALTAR", "name": "Strait of Gibraltar", "lat": 35.95, "lon": -5.6},
    {"_key": "BABELMANDEB", "name": "Bab-el-Mandeb", "lat": 12.6, "lon": 43.4},
    {"_key": "HORMUZ", "name": "Strait of Hormuz", "lat": 26.57, "lon": 56.25},
    {"_key": "GOODHOPE", "name": "Cape of Good Hope", "lat": -34.36, "lon": 18.47},
)

# --------------------------------------------------------------------------- #
# Synthetic-weight estimation constants. transit_time_hours = distance_nm /
# assumed service speed; a typical container-ship service speed is ~18 knots
# (nautical miles / hour). distance_nm itself is great-circle (haversine) over the
# port centroids — a geographic estimate (D-08) where a real leg is NOT observed.
# --------------------------------------------------------------------------- #
ASSUMED_SERVICE_SPEED_KNOTS: float = 18.0

# Fallback per-port centroids (deg) for the synthetic distance estimate when the
# Silver dim_port coords are unavailable at row-build time (offline construction).
# These mirror data_gen/network.PORT_COUNTRY's port set; they are coarse port-city
# centroids used ONLY for the synthetic distance estimate, never for the real
# (Silver-conformed) dim_port coordinates which always win when present.
_PORT_CENTROID_FALLBACK: dict[str, tuple[float, float]] = {
    "USHOU": (29.75, -95.30),
    "USLAX": (33.74, -118.27),
    "USNYC": (40.70, -74.02),
    "USSAV": (32.08, -81.09),
    "CNSHA": (31.23, 121.47),
    "JPTYO": (35.65, 139.84),
    "DEHAM": (53.55, 9.99),
    "KRPUS": (35.10, 129.04),
    "NLRTM": (51.95, 4.14),
}


# --------------------------------------------------------------------------- #
# Pure row builders — deterministic, side-effect-free, OFFLINE-testable.       #
# --------------------------------------------------------------------------- #
def _json_safe(val: Any) -> Any:
    """Coerce a Silver column value to a JSON-serializable form for the Arango sink.

    The SCD2 dims (``dim_vessel`` / ``dim_carrier``) carry ``effective_from`` /
    ``effective_to`` as BigQuery/Parquet DATE columns, which ``pyarrow.Table.to_pylist``
    materializes as :class:`datetime.date` / :class:`datetime.datetime` — python-arango's
    JSON serializer raises ``TypeError: Object of type date is not JSON serializable`` on
    these. Coerce date/datetime to a stable ISO-8601 string (the value is preserved, not
    dropped — the vertex stays a faithful projection of the conformed dim) and leave all
    other types untouched. Deterministic (no ``now()``), so the offline builders stay pure.
    """
    if isinstance(val, (_dt.date, _dt.datetime)):
        return val.isoformat()
    return val


def build_port_vertex(row: dict[str, Any]) -> dict[str, Any]:
    """Build one ``ports`` vertex; ``_key`` == the conformed UN/LOCODE (D-11).

    Carries ``lat``/``lon`` (the WPI centroid) and the Silver ``provenance`` flag
    through unchanged. Extra Silver columns (e.g. surrogate_key) are preserved so
    the graph vertex stays a faithful projection of the conformed dim.
    """
    unlocode = row["unlocode"]
    vtx: dict[str, Any] = {"_key": unlocode}
    for col, val in row.items():
        if col == "unlocode":
            continue
        vtx[col] = _json_safe(val)
    return vtx


def build_port_vertices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build all ``ports`` vertices, order-stable (idempotent UPSERT contract)."""
    return [build_port_vertex(r) for r in rows]


def build_vessel_vertices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build ``vessels`` vertices; ``_key`` == IMO (the conformed natural key)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        imo = row["imo"]
        vtx: dict[str, Any] = {"_key": str(imo)}
        for col, val in row.items():
            if col == "imo":
                continue
            vtx[col] = _json_safe(val)
        out.append(vtx)
    return out


def build_carrier_vertices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build ``carriers`` vertices; ``_key`` == SCAC (the conformed natural key)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        scac = row["scac"]
        vtx: dict[str, Any] = {"_key": scac}
        for col, val in row.items():
            if col == "scac":
                continue
            vtx[col] = _json_safe(val)
        out.append(vtx)
    return out


def lane_key(origin: str, dest: str) -> str:
    """Deterministic lane / route ``_key`` for a directed port-pair."""
    return f"{origin}__{dest}"


def build_lane_vertices(lanes: tuple[tuple[str, str], ...] = LANES) -> list[dict[str, Any]]:
    """Build ``lanes`` vertices (one per directed port-pair lane).

    ``_key`` == origin+dest UN/LOCODE (M2). A lane vertex is the from-side of a
    ``transits_chokepoint`` edge; it mirrors each ``route`` edge structurally.
    Order follows the fixed ``LANES`` order for byte-stability.
    """
    return [
        {
            "_key": lane_key(o, d),
            "origin": o,
            "dest": d,
            "origin_country": PORT_COUNTRY.get(o),
            "dest_country": PORT_COUNTRY.get(d),
        }
        for (o, d) in lanes
    ]


def build_chokepoint_vertices() -> list[dict[str, Any]]:
    """Build the curated ``chokepoints`` vertex set (D-09). Order-stable."""
    return [dict(cp) for cp in CHOKEPOINTS]


def _port_centroid(code: str, coords: dict[str, tuple[float, float]] | None) -> tuple[float, float] | None:
    """Resolve a port centroid: prefer the live Silver coords, else the fallback."""
    if coords and code in coords:
        return coords[code]
    return _PORT_CENTROID_FALLBACK.get(code)


def _synthetic_distance_nm(
    origin: str, dest: str, coords: dict[str, tuple[float, float]] | None
) -> float | None:
    """Great-circle distance (nm) between two port centroids, or ``None`` if unknown."""
    a = _port_centroid(origin, coords)
    b = _port_centroid(dest, coords)
    if a is None or b is None:
        return None
    return round(haversine_nm(a[0], a[1], b[0], b[1]), 2)


def build_route_edge(
    origin: str,
    dest: str,
    *,
    transit_time_hours: float | None = None,
    distance_nm: float | None = None,
    service_frequency: float | None = None,
    reliability_score: float | None = None,
    expected_delay: float | None = None,
    weight_provenance: str = "synthetic",
    port_coords: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Build one ``route`` edge with the four LOCKED D-08 weights + provenance.

    ``_key`` == ``f"{origin}__{dest}"``; ``_from`` == ``ports/{origin}``;
    ``_to`` == ``ports/{dest}``. Where a weight is not supplied it is estimated
    geographically/synthetically (``distance_nm`` via haversine, ``transit_time_hours``
    via distance / assumed service speed). ``weight_provenance`` is "real" only when
    a weight was overlaid from an observed ``fact_voyage_leg`` (US->US only,
    Pitfall 4) else "synthetic" — mirroring the Silver provenance discipline.
    """
    if distance_nm is None:
        distance_nm = _synthetic_distance_nm(origin, dest, port_coords)
    if transit_time_hours is None and distance_nm is not None:
        transit_time_hours = round(distance_nm / ASSUMED_SERVICE_SPEED_KNOTS, 2)
    return {
        "_key": lane_key(origin, dest),
        "_from": f"ports/{origin}",
        "_to": f"ports/{dest}",
        "transit_time_hours": transit_time_hours,
        "distance_nm": distance_nm,
        "service_frequency": service_frequency,
        "reliability_score": reliability_score,
        "expected_delay": expected_delay,
        "weight_provenance": weight_provenance,
    }


def build_route_edges(
    lanes: tuple[tuple[str, str], ...] = LANES,
    *,
    real_overlay: dict[tuple[str, str], dict[str, float]] | None = None,
    service_frequency: dict[tuple[str, str], float] | None = None,
    reliability: dict[str, dict[str, float]] | None = None,
    port_coords: dict[str, tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    """Build all ``route`` edges, order-stable (idempotent UPSERT contract).

    ``real_overlay`` maps a lane -> observed weights (transit_time_hours/distance_nm)
    from aggregated ``fact_voyage_leg``; lanes present in it are tagged
    ``weight_provenance="real"`` (US->US only — Pitfall 4), all others "synthetic".
    ``service_frequency`` (LSCI priors) and ``reliability`` (LPI priors, keyed by
    dest country) feed the remaining two D-08 weights.
    """
    real_overlay = real_overlay or {}
    service_frequency = service_frequency or {}
    reliability = reliability or {}
    out: list[dict[str, Any]] = []
    for (o, d) in lanes:
        observed = real_overlay.get((o, d))
        rel = reliability.get(PORT_COUNTRY.get(d, ""), {})
        out.append(
            build_route_edge(
                o,
                d,
                transit_time_hours=(observed or {}).get("transit_time_hours"),
                distance_nm=(observed or {}).get("distance_nm"),
                service_frequency=service_frequency.get((o, d)),
                reliability_score=rel.get("reliability_score"),
                expected_delay=rel.get("expected_delay"),
                weight_provenance="real" if observed else "synthetic",
                port_coords=port_coords,
            )
        )
    return out


def build_calls_at_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build ``calls_at`` edges (vessels -> ports) from (imo, unlocode) rows.

    ``_key`` == ``f"{imo}__{unlocode}"``; structural (which ports a vessel serves).
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        imo = str(row["imo"])
        port = row["unlocode"]
        out.append(
            {
                "_key": f"{imo}__{port}",
                "_from": f"vessels/{imo}",
                "_to": f"ports/{port}",
            }
        )
    return out


def build_operates_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build ``operates`` edges (carriers -> vessels) from (scac, imo) rows.

    ``_key`` == ``f"{scac}__{imo}"``. Synthetic assignment (AIS has no operator
    field — D-09); the SCAC set is the conformed ``CARRIER_SCACS``.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        scac = row["scac"]
        imo = str(row["imo"])
        out.append(
            {
                "_key": f"{scac}__{imo}",
                "_from": f"carriers/{scac}",
                "_to": f"vessels/{imo}",
            }
        )
    return out


def chokepoints_for_lane(origin: str, dest: str) -> tuple[str, ...]:
    """Deterministic geographic rule: which chokepoints a lane transits (D-09).

    Keyed on ``(PORT_COUNTRY[origin], PORT_COUNTRY[dest])`` -> chokepoint set,
    direction-insensitive (a lane and its reverse transit the same chokepoints).
    A fixed dict lookup is preferred over GEO_DISTANCE for determinism (RESEARCH
    Pattern 3). Returns ``()`` for unmapped pairs (no edge emitted). Rationale:
      * Far-East (CHN/JPN/KOR) <-> US-East (NYC/SAV) -> Suez OR Panama (Asia-USEC).
      * Far-East <-> US-West (LAX) / US-Gulf (HOU) -> trans-Pacific, no canal.
      * Europe (DEU/NLD) <-> US-East -> Gibraltar (Med approach) for the trans-Atlantic.
      * Europe <-> US-West/Gulf -> Panama (Atlantic->Pacific) or Gibraltar.
    """
    co = PORT_COUNTRY.get(origin)
    cd = PORT_COUNTRY.get(dest)
    if co is None or cd is None:
        return ()
    far_east = {"CHN", "JPN", "KOR"}
    europe = {"DEU", "NLD"}
    us_east_ports = {"USNYC", "USSAV"}
    us_westgulf_ports = {"USLAX", "USHOU"}

    # Normalize to (foreign, us) regardless of direction.
    if co == "USA":
        us_port, foreign_country = origin, cd
    elif cd == "USA":
        us_port, foreign_country = dest, co
    else:
        return ()  # US<->foreign lanes only (LANES never connects two foreigns)

    is_us_east = us_port in us_east_ports
    is_us_westgulf = us_port in us_westgulf_ports

    if foreign_country in far_east:
        if is_us_east:
            return ("SUEZ", "PANAMA")
        return ()  # trans-Pacific: no curated canal transit
    if foreign_country in europe:
        if is_us_east:
            return ("GIBRALTAR",)
        if is_us_westgulf:
            return ("GIBRALTAR", "PANAMA")
    return ()


def build_transits_chokepoint_edges(
    lanes: tuple[tuple[str, str], ...] = LANES,
) -> list[dict[str, Any]]:
    """Build ``transits_chokepoint`` edges (lanes -> chokepoints), rule-based (D-09).

    ``_from`` == ``lanes/{origin}__{dest}``; ``_to`` == ``chokepoints/{cp}``;
    ``_key`` == ``f"{origin}__{dest}__{cp}"``. Order-stable: lanes in fixed LANES
    order, chokepoints in the deterministic rule's order.
    """
    out: list[dict[str, Any]] = []
    for (o, d) in lanes:
        lk = lane_key(o, d)
        for cp in chokepoints_for_lane(o, d):
            out.append(
                {
                    "_key": f"{lk}__{cp}",
                    "_from": f"lanes/{lk}",
                    "_to": f"chokepoints/{cp}",
                }
            )
    return out


# --------------------------------------------------------------------------- #
# Idempotent structure creation + UPSERT (live cluster — exercised in 06-05).  #
# --------------------------------------------------------------------------- #
def ensure_structure(db: Any) -> None:
    """Create-if-absent the 5 vertex + 4 edge collections, the named graph, and
    the chokepoint vertex-centric index — all idempotent.

    Never drops or wipes existing structure (T-06-05). The named graph uses the
    LOCKED M2 edge definitions verbatim (docs/deck/m2-arango-graph.md).
    """
    for name in VERTEX_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name)
            print(f"[OK] created vertex collection {name}")
    for name in EDGE_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name, edge=True)
            print(f"[OK] created edge collection {name}")

    if not db.has_graph(GRAPH_NAME):
        db.create_graph(GRAPH_NAME, edge_definitions=EDGE_DEFINITIONS)
        print(f"[OK] created named graph {GRAPH_NAME}")

    # Vertex-centric persistent index on the chokepoint supernode edge endpoint.
    choke = db.collection("transits_chokepoint")
    existing = {idx.get("name") for idx in choke.indexes()}
    if VC_CHOKE_INDEX_NAME not in existing:
        choke.add_persistent_index(fields=["_to"], name=VC_CHOKE_INDEX_NAME)
        print(f"[OK] created index {VC_CHOKE_INDEX_NAME} on transits_chokepoint")


def upsert_rows(db: Any, collection: str, rows: list[dict[str, Any]], *, edge: bool = False) -> int:
    """Idempotently UPSERT ``rows`` into ``collection`` keyed on ``_key``.

    LOCKED idempotency pattern: ``UPSERT { _key } INSERT row UPDATE row`` — NEVER
    wipe-then-reload (the ``insert_many`` after a collection wipe is the Phase-5
    CR-02/CR-03 wipe-race lesson; threat T-06-05) — that call is forbidden here.
    ``rows`` and the collection are AQL BIND variables, never
    f-string-interpolated (threat T-06-06 / ASVS V5). ``edge`` is accepted for a
    uniform call signature across vertex/edge collections. Returns the row count.
    """
    if not rows:
        return 0
    db.aql.execute(
        "FOR row IN @rows "
        "UPSERT { _key: row._key } INSERT row UPDATE row IN @@collection",
        bind_vars={"rows": rows, "@collection": collection},
    )
    return len(rows)


# --------------------------------------------------------------------------- #
# Silver readers (live GCS read — same idiom as scripts/verify.py).            #
# --------------------------------------------------------------------------- #
def _read_silver_dim(bucket: str, dim_prefix: str) -> list[dict[str, Any]]:
    """Read a landed ``silver/{dim}`` Parquet snapshot into a list of row dicts.

    Mirrors scripts/verify.py ``_read_silver_table``: lazy-import pyarrow +
    google-cloud-storage, list the ``.parquet`` blobs under the prefix, read them
    into pyarrow Tables, and convert to plain dicts. Returns ``[]`` if absent.
    """
    import pyarrow.parquet as pq
    from google.cloud import storage

    client = storage.Client(project="data-architecture-msds683")
    blobs = sorted(
        (b for b in client.list_blobs(bucket, prefix=dim_prefix) if b.name.endswith(".parquet")),
        key=lambda b: b.name,
    )
    rows: list[dict[str, Any]] = []
    for blob in blobs:
        table = pq.read_table(io.BytesIO(blob.download_as_bytes()))
        rows.extend(table.to_pylist())
    return rows


def load_graph(bucket: str = BUCKET) -> dict[str, int]:
    """Project conformed Silver dims + the synthetic lane network into ocean_network.

    The single entrypoint callable from BOTH the DAG ``load_arango`` task and the
    ``make load-arango`` target (D-06a). Reads the landed ``silver/dim_*`` Parquet
    (real ports/vessels/carriers — the conformed-key bridge) and the ``data_gen``
    constants (the synthetic priors-conditioned lane network), builds the vertex /
    edge rows via the pure builders above, and idempotently UPSERTs each collection
    by deterministic ``_key``. Returns a per-collection count summary dict.

    Connects ONLY via :func:`lib.arango_client.get_db` (env creds, TLS-on); prints
    only ``[INFO]``/``[OK]`` counts, never credentials.
    """
    from lib.arango_client import get_db

    db = get_db(request_timeout=120)
    ensure_structure(db)

    # --- Vertices: conformed real Silver dims (the D-11 bridge) ------------- #
    port_rows = _read_silver_dim(bucket, "silver/dim_port")
    vessel_rows = [r for r in _read_silver_dim(bucket, "silver/dim_vessel") if r.get("is_current", True)]
    carrier_rows = [r for r in _read_silver_dim(bucket, "silver/dim_carrier") if r.get("is_current", True)]

    ports = build_port_vertices(port_rows)
    vessels = build_vessel_vertices(vessel_rows)
    carriers = build_carrier_vertices(carrier_rows)
    lanes = build_lane_vertices(LANES)
    chokepoints = build_chokepoint_vertices()

    # Live port centroids from the conformed dim_port (real coords win over fallback).
    port_coords = {p["_key"]: (p["lat"], p["lon"]) for p in ports if "lat" in p and "lon" in p}

    # --- Edges: synthetic priors-conditioned lane network ------------------- #
    # service_frequency from the schedules generator (LSCI priors); reliability/
    # expected_delay are conditioned per-country (LPI priors) by run_criticality/UC
    # analytics downstream — here we project structure + the geographic estimates.
    routes = build_route_edges(LANES, port_coords=port_coords)
    # US->US proforma lanes are the only place a REAL voyage-leg overlay is possible
    # (Pitfall 4 — the AIS slice is US-only); they are also emitted as routes so a
    # real overlay has somewhere to land in 06-05's verify reconciliation.
    us_routes = build_route_edges(US_US_LANES, port_coords=port_coords)
    calls_at = build_calls_at_edges([{"imo": r["imo"], "unlocode": u} for r in vessel_rows for u in _vessel_ports(r)])
    operates = build_operates_edges(_operates_rows(vessel_rows, carrier_rows))
    transits = build_transits_chokepoint_edges(LANES)

    summary: dict[str, int] = {}
    summary["ports"] = upsert_rows(db, "ports", ports)
    summary["vessels"] = upsert_rows(db, "vessels", vessels)
    summary["carriers"] = upsert_rows(db, "carriers", carriers)
    summary["lanes"] = upsert_rows(db, "lanes", lanes)
    summary["chokepoints"] = upsert_rows(db, "chokepoints", chokepoints)
    summary["route"] = upsert_rows(db, "route", routes + us_routes, edge=True)
    summary["calls_at"] = upsert_rows(db, "calls_at", calls_at, edge=True)
    summary["operates"] = upsert_rows(db, "operates", operates, edge=True)
    summary["transits_chokepoint"] = upsert_rows(db, "transits_chokepoint", transits, edge=True)

    for coll, n in summary.items():
        print(f"[INFO] upserted {n} into {coll}")
    print(f"[OK] load_graph complete: {summary}")
    return summary


def _vessel_ports(vessel_row: dict[str, Any]) -> list[str]:
    """Resolve the ports a vessel structurally calls at.

    Prefers an explicit ``ports`` / ``called_ports`` list on the conformed row;
    falls back to the four real US AIS ports (the slice every vessel was observed
    in — D-04). Deterministic order.
    """
    for col in ("called_ports", "ports"):
        val = vessel_row.get(col)
        if isinstance(val, (list, tuple)) and val:
            return list(val)
    return ["USHOU", "USLAX", "USNYC", "USSAV"]


def _operates_rows(
    vessel_rows: list[dict[str, Any]], carrier_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Resolve (scac, imo) operates assignments.

    Prefers an explicit ``scac`` on the conformed vessel row (the synthetic
    operated_by assignment landed in Silver, OPERATED_BY_OFFSET). Falls back to a
    deterministic round-robin over CARRIER_SCACS so every vessel has exactly one
    operator (AIS has no operator field — D-09). Order follows vessel_rows.
    """
    scacs = [r["scac"] for r in carrier_rows] or list(CARRIER_SCACS)
    out: list[dict[str, Any]] = []
    for i, v in enumerate(vessel_rows):
        scac = v.get("scac") or scacs[i % len(scacs)]
        out.append({"scac": scac, "imo": v["imo"]})
    return out
