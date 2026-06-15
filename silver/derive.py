"""silver/derive.py — derive the two REAL facts from geofenced AIS port calls.

ETL-01 / criterion 2: BOTH real facts are derived from AIS POSITIONS via the
geofence state machine (silver.geofence) — never from AIS free-text destination
(D-02). Two pure, deterministic, offline-testable transforms (Pattern 1 split —
no I/O here; landing is the separate land_silver step):

  - ``derive_fact_port_calls(calls, port_centroids)`` -> ``fact_port_call`` rows.
    Consumes the geofence state machine's call dicts (``imo, unlocode,
    arrival_ts, departure_ts``), attaches the conformed UN/LOCODE port centroid
    lat/lon (from the conformed ``dim_port``, NOT AIS destination text — D-02),
    a ``dt`` partition date = ARRIVAL date (Pitfall 4 — never split a
    midnight-spanning fact), and ``provenance="real"`` (D-11).

  - ``derive_voyage_legs(calls, port_centroids, schedules=...)`` -> ``fact_voyage_leg``
    rows. Pairs each vessel's consecutive calls (A->B = one leg, RESEARCH
    Pattern 4 / D-10): sort by (imo, arrival_ts), group by IMO, pair consecutive.
    Each leg carries ``transit_hours = (b.arrival - a.departure)/3600``,
    ``distance_nm = haversine_nm`` between the two port centroids (great-circle,
    D-10 — reuses silver.haversine), a ``schedule_delta`` joined to the synthetic
    proforma where a lane matches (else NaN/None — Pitfall 8, the documented
    real/synthetic seam: real US->US legs lack a matching synthetic-international
    proforma lane; we do NOT fabricate one), a ``dt`` partition date =
    ORIGIN-DEPARTURE date (Pitfall 4), and ``provenance="real"``.

Edge cases (Pitfall 7): a single-call vessel emits ZERO legs (no pair);
same-port consecutive calls emit a leg with ``distance_nm == 0`` (kept + counted
per the documented policy). Both functions are PURE (in-memory in, list[dict]
out, no I/O) so they are unit-testable fully offline.

Provenance: 04-RESEARCH.md § Architecture Patterns Pattern 4 (voyage-leg pairing)
+ D-10 + Pitfall 4 (per-fact partition key) + Pitfall 7 (single-call/zero-distance)
+ Pitfall 8 (schedule_delta NaN on unmatched lane); 04-PATTERNS.md § silver/derive.py
(canonical fixed-order row constructor mirroring data_gen/schedules.py::_schedule_row;
deterministic fixed-order emission). Reuses silver.haversine.haversine_nm and the
silver.geofence.derive_port_calls output shape.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from silver.haversine import haversine_nm

# Proforma transit_days -> transit_hours conversion (D-10 / schedules.py).
_HOURS_PER_DAY = 24.0


def _port_call_row(
    imo: str,
    unlocode: str,
    arrival_ts,
    departure_ts,
    lat: float,
    lon: float,
    dt_partition,
    provenance: str,
) -> dict:
    """Canonical key order for a fact_port_call row (locks emission determinism)."""
    return {
        "vessel_imo": imo,
        "unlocode": unlocode,
        "arrival_ts": arrival_ts,
        "departure_ts": departure_ts,
        "lat": lat,
        "lon": lon,
        "dt": dt_partition,
        "provenance": provenance,
    }


def _voyage_leg_row(
    vessel_imo: str,
    origin_unlocode: str,
    dest_unlocode: str,
    transit_hours: float,
    distance_nm: float,
    schedule_delta,
    dt_partition,
    provenance: str,
) -> dict:
    """Canonical key order for a fact_voyage_leg row (locks emission determinism)."""
    return {
        "vessel_imo": vessel_imo,
        "origin_unlocode": origin_unlocode,
        "dest_unlocode": dest_unlocode,
        "transit_hours": transit_hours,
        "distance_nm": distance_nm,
        "schedule_delta": schedule_delta,
        "dt": dt_partition,
        "provenance": provenance,
    }


def derive_fact_port_calls(
    calls: Iterable[Mapping],
    port_centroids: Mapping[str, tuple],
) -> list[dict]:
    """Derive ``fact_port_call`` rows from geofenced calls (positions-only, D-02).

    ``calls`` are the silver.geofence state-machine output dicts
    (``imo, unlocode, arrival_ts, departure_ts``). ``port_centroids`` maps the
    conformed UN/LOCODE -> (lat, lon) centroid (from the conformed dim_port —
    NOT AIS destination text). Each emitted fact carries the centroid lat/lon,
    a ``dt`` partition = arrival date (Pitfall 4), and ``provenance="real"``
    (D-11). A call whose UN/LOCODE has no known centroid fails loud (a
    derivation must not invent a position).

    Returns a list of fact_port_call dicts in input order (deterministic).
    """
    facts: list[dict] = []
    for c in calls:
        unlocode = c["unlocode"]
        if unlocode not in port_centroids:
            raise ValueError(
                f"port call references UN/LOCODE {unlocode!r} with no conformed "
                "dim_port centroid (D-02) — cannot derive fact_port_call."
            )
        lat, lon = port_centroids[unlocode]
        arrival_ts = c["arrival_ts"]
        facts.append(
            _port_call_row(
                imo=c["imo"],
                unlocode=unlocode,
                arrival_ts=arrival_ts,
                departure_ts=c["departure_ts"],
                lat=lat,
                lon=lon,
                dt_partition=arrival_ts.date(),  # partition by ARRIVAL date
                provenance="real",
            )
        )
    return facts


def _build_proforma_index(
    schedules: Sequence[Mapping] | None,
) -> dict[tuple[str, str], float]:
    """Index synthetic proforma transit_hours by (origin_unlocode, dest_unlocode).

    ``transit_days * 24 = proforma transit_hours`` (D-10 / data_gen.schedules).
    If multiple proforma rows share a lane, the LAST one wins (deterministic in
    input order). Returns an empty index for ``None``/empty schedules.
    """
    index: dict[tuple[str, str], float] = {}
    if not schedules:
        return index
    for s in schedules:
        lane = (s["origin_unlocode"], s["dest_unlocode"])
        index[lane] = float(s["transit_days"]) * _HOURS_PER_DAY
    return index


def derive_voyage_legs(
    calls: Iterable[Mapping],
    port_centroids: Mapping[str, tuple],
    *,
    schedules: Sequence[Mapping] | None = None,
) -> list[dict]:
    """Pair each vessel's consecutive port calls into ``fact_voyage_leg`` rows (D-10).

    Sort calls by (imo, arrival_ts), group by IMO, pair consecutive calls
    (a->b = one leg). Each leg: ``transit_hours = (b.arrival - a.departure) in
    hours``, ``distance_nm = haversine_nm`` between the two port centroids
    (great-circle, D-10), ``schedule_delta = transit_hours - proforma_hours``
    joined on (origin, dest) where a synthetic proforma lane matches else
    ``None``/NaN (Pitfall 8 — the real/synthetic seam; do NOT fabricate a
    proforma), ``dt`` partition = origin-departure date (Pitfall 4), and
    ``provenance="real"`` (D-11).

    Edge cases (Pitfall 7): a single-call vessel emits ZERO legs; same-port
    consecutive calls emit a leg with ``distance_nm == 0`` (kept + counted).

    Returns a list of fact_voyage_leg dicts in deterministic (vessel, leg) order.
    """
    proforma = _build_proforma_index(schedules)

    # Group calls per vessel (resolved IMO), preserving order; sort by arrival.
    per_vessel: dict[str, list[Mapping]] = {}
    for c in calls:
        per_vessel.setdefault(c["imo"], []).append(c)

    legs: list[dict] = []
    for imo in sorted(per_vessel.keys()):
        rows = sorted(per_vessel[imo], key=lambda r: r["arrival_ts"])
        # Pair consecutive calls a -> b. A single call yields no pair (Pitfall 7).
        for a, b in zip(rows, rows[1:]):
            origin = a["unlocode"]
            dest = b["unlocode"]
            transit_hours = (b["arrival_ts"] - a["departure_ts"]).total_seconds() / 3600.0
            a_lat, a_lon = port_centroids[origin]
            b_lat, b_lon = port_centroids[dest]
            distance_nm = haversine_nm(a_lat, a_lon, b_lat, b_lon)
            proforma_hours = proforma.get((origin, dest))
            # Pitfall 8: NaN/None where no synthetic proforma lane matches — do
            # NOT fabricate a delta. Populate only on a matched lane.
            schedule_delta = (
                transit_hours - proforma_hours if proforma_hours is not None else None
            )
            legs.append(
                _voyage_leg_row(
                    vessel_imo=imo,
                    origin_unlocode=origin,
                    dest_unlocode=dest,
                    transit_hours=transit_hours,
                    distance_nm=distance_nm,
                    schedule_delta=schedule_delta,
                    dt_partition=a["departure_ts"].date(),  # origin-departure date
                    provenance="real",
                )
            )
    return legs
