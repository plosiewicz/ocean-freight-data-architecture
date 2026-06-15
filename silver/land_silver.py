"""silver/land_silver.py — orchestrate Bronze read -> conform + derive -> idempotent Silver land.

ETL-01 / D-07 (the Silver layer is the SINGLE SOURCE OF TRUTH — ONE transform, TWO
sinks: Phase-5 BigQuery star + Phase-6 ArangoDB graph both read here, never from
each other) / D-08 (dims land as SNAPSHOTS with NO ``dt=``; the two real facts land
under ``dt=YYYY-MM-DD/`` keyed on each fact's OWN event date).

This is the only network-touching Silver step (the Pattern-1 pure-transform /
idempotent-land split, reused from Phase 3). The pure transforms — ``silver.identity``
(MMSI->IMO resolution + DQ counts), ``silver.geofence`` (port-call state machine),
``silver.conform`` (the four conformed dims + SCD), ``silver.derive`` (the two real
facts) — take in-memory inputs and return rows; this orchestrator wires them to the
landed Bronze inputs and lands the results via ``lib.gcs.upload_if_absent``
(write-once, no-op-if-exists — the Bronze immutability contract, D-06/D-09; threat
T-04-13). A second run lands 0 new objects (the ``silver_idempotency`` ship-gate).

Pipeline:
  1. read Bronze AIS ``ais/dt=*/*.parquet`` column-projected (mmsi, base_date_time,
     imo, geometry) -> ``silver.identity.resolve_mmsi_to_imo`` (collision + no-IMO
     drop counts, D-05/D-06) -> rekey position fixes by RESOLVED IMO (D-04).
  2. ``silver.geofence.derive_port_calls`` over the IMO-keyed fixes against the four
     US-port circular fences (D-01/D-02/D-03 radius + min-dwell — a CALIBRATION
     artifact, the final values are PRINTed by the verify gate, not asserted).
  3. ``silver.conform`` the four real dims (dim_port SCD1 from the four port
     centroids; dim_lane SCD1 from the conformed international lanes; dim_vessel
     SCD2 from the resolved-IMO vessel snapshot; dim_carrier SCD2 reference-assigned)
     anchored to a DETERMINISTIC ``run_date`` = the slice's max event date, NEVER
     wall-clock time (threat T-04-07).
  4. ``silver.derive`` both real facts from the geofenced calls (positions-only,
     D-02): ``fact_port_call`` (dt = arrival date) and ``fact_voyage_leg`` (dt =
     origin-departure date), schedule_delta joined to the synthetic proforma where a
     lane matches else None (Pitfall 8).
  5. land dims as snapshots (no dt=) and facts under per-record ``dt=`` partitions via
     ``upload_if_absent``; mirror ``scripts.load_bronze._record_dt`` fail-loud-on-
     missing-partition-date (CR-03) — never split a midnight-spanning fact (Pitfall 4).

Provenance: scripts/load_bronze.py (per-record dt= partition + upload_if_absent loop
+ _strip_gs + _record_dt + the EXACT ``complete: N landed, M skipped`` summary line —
the verify idempotency gate parses this wording); ingest/pull_ais.py::land_day
(write-local-Parquet-then-upload); 04-PATTERNS.md § silver/land_silver.py; 04-RESEARCH.md
§ Architecture Patterns (Silver layout lines 162-171) D-07/D-08; CLAUDE.md §5
staging-is-the-contract.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import lib.gcs
from data_gen.network import LANES
from ingest.pull_ais import PORT_BBOXES
from silver import conform, derive, geofence, identity

BRONZE_BUCKET_DEFAULT = "data-architecture-msds683-bronze"
AIS_PREFIX = "ais/"
# Bronze AIS columns the identity + geofence transforms need (column-projected read).
AIS_READ_COLUMNS = ["mmsi", "base_date_time", "imo", "geometry"]

# D-03 documented geofence calibration (radius + min-dwell). These are the FINAL
# calibrated values for the bounded 7-day 4-port slice — the resulting port-call /
# leg counts are a calibration artifact PRINTed by the verify gate, not asserted to
# a fixed number. Reuse the silver.geofence documented defaults so a single constant
# governs both derivation and the verify [CITE] line.
RADIUS_NM = geofence.DEFAULT_RADIUS_NM
MIN_DWELL_HOURS = geofence.DEFAULT_MIN_DWELL_HOURS

# Silver object keys (D-08). Dims = snapshots, NO dt=. Facts = dt=YYYY-MM-DD/.
DIM_KEYS: dict[str, str] = {
    "dim_port": "silver/dim_port/dim_port.parquet",
    "dim_vessel": "silver/dim_vessel/dim_vessel.parquet",
    "dim_carrier": "silver/dim_carrier/dim_carrier.parquet",
    "dim_lane": "silver/dim_lane/dim_lane.parquet",
}
FACT_PREFIXES: dict[str, str] = {
    "fact_port_call": "silver/fact_port_call",
    "fact_voyage_leg": "silver/fact_voyage_leg",
}


def _strip_gs(bucket: str) -> str:
    """Accept either ``gs://name`` (Makefile) or a bare ``name``; return bare name."""
    if bucket.startswith("gs://"):
        return bucket[len("gs://"):].rstrip("/")
    return bucket.rstrip("/")


def port_centroids_from_bboxes() -> dict[str, tuple[float, float]]:
    """Conformed UN/LOCODE -> (lat, lon) centroid from the four PORT_BBOXES midpoints.

    The four US-port centroids are the midpoints of the Phase-3 PORT_BBOXES boxes
    (the exact region AIS was filtered to at landing) — so the circular fences sit
    inside the landed slice and align with where the positions actually are. These
    are real reference coordinates (the bounding boxes are RESEARCH-verified /
    defensible coastal boxes) and pass the conform centroid-in-bbox sanity assertion
    by construction.
    """
    centroids: dict[str, tuple[float, float]] = {}
    for code, (lon_min, lon_max, lat_min, lat_max) in PORT_BBOXES.items():
        lat = (lat_min + lat_max) / 2.0
        lon = (lon_min + lon_max) / 2.0
        centroids[code] = (lat, lon)
    return centroids


def _record_dt(record: dict, date_field: str, *, source: str) -> str:
    """Return the ``dt=`` partition date (``YYYY-MM-DD``) for one fact record.

    Read ``date_field`` (a ``datetime.date``/``datetime`` or ISO string) and take
    its calendar date. Fail loud if the field is missing/unparseable — never route a
    fact to a wrong or default partition silently (CR-03 / Pitfall 4 — never split a
    midnight-spanning fact).
    """
    raw = record.get(date_field)
    if isinstance(raw, dt.datetime):
        return raw.date().isoformat()
    if isinstance(raw, dt.date):
        return raw.isoformat()
    if isinstance(raw, str) and len(raw) >= 10:
        return raw[:10]
    raise ValueError(
        f"{source}: record missing/short {date_field!r} (got {raw!r}) — cannot "
        "derive dt= partition (CR-03 / Pitfall 4)."
    )


def _is_real_mmsi(mmsi) -> bool:
    """True iff ``mmsi`` is a real vessel MMSI (not a null/0/empty placeholder).

    WR-06: AIS rows can carry a null, 0, or empty MMSI (non-vessel / malformed
    records). Such rows must NOT count toward the MMSI universe used for the
    no-IMO drop denominator (D-06), or the deck-cited drop count is inflated by
    non-vessel rows. A real MMSI is a non-empty, non-zero numeric identifier.
    """
    if mmsi is None:
        return False
    s = str(mmsi).strip()
    if not s:
        return False
    # Treat a purely-zero MMSI ("0", "000000000") as a placeholder, not a vessel.
    if s.lstrip("0") == "":
        return False
    return True


def _normalize_imo(raw):
    """Strip the Bronze AIS ``IMO`` prefix to a bare 7-digit IMO (or None).

    MarineCadastre 2024 AIS encodes the static IMO as ``"IMO9840879"`` (an ``IMO``
    prefix + the 7 digits), and empty fixes as ``""``. ``silver.imo.valid_imo`` /
    ``silver.identity`` correctly require a BARE 7-digit IMO natural key (D-04), so
    the prefix must be removed at the read boundary — keeping the pure transforms
    encoding-agnostic. Returns the bare digit string, or None for empty/missing.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.upper().startswith("IMO"):
        s = s[3:].strip()
    return s or None


def read_ais_fixes(bucket: str) -> tuple[list[tuple], list[tuple]]:
    """Read column-projected Bronze AIS -> identity rows + position fixes.

    Returns ``(identity_rows, position_fixes)`` where ``identity_rows`` are
    ``(mmsi, imo_or_none, ts)`` for ``resolve_mmsi_to_imo`` (with the Bronze ``IMO``
    prefix stripped to a bare 7-digit natural key, D-04) and ``position_fixes`` are
    ``(mmsi, wkb_or_none, ts)`` to be rekeyed by RESOLVED IMO before the geofence
    state machine. Reads every ``ais/dt=*/*.parquet`` object once.
    """
    client = lib.gcs.get_client()
    gbucket = client.bucket(bucket)
    blobs = [b for b in client.list_blobs(gbucket, prefix=AIS_PREFIX) if b.name.endswith(".parquet")]
    if not blobs:
        raise RuntimeError(
            f"no landed AIS objects under gs://{bucket}/{AIS_PREFIX}dt=*/...parquet "
            "(run `make pull-ais` first)."
        )

    identity_rows: list[tuple] = []
    position_fixes: list[tuple] = []
    import io

    for blob in sorted(blobs, key=lambda b: b.name):
        table = pq.read_table(io.BytesIO(blob.download_as_bytes()), columns=AIS_READ_COLUMNS)
        mmsis = table.column("mmsi").to_pylist()
        imos = table.column("imo").to_pylist()
        ts = table.column("base_date_time").to_pylist()
        geom = table.column("geometry").to_pylist()
        for m, i, t, g in zip(mmsis, imos, ts, geom):
            identity_rows.append((m, _normalize_imo(i), t))
            position_fixes.append((m, g, t))
    return identity_rows, position_fixes


def _vessel_snapshot_from_mapping(mapping: dict) -> pd.DataFrame:
    """Build the dim_vessel SCD2 snapshot from resolved IMOs (deterministic).

    AIS carries no vessel name; we synthesize a stable label from the IMO so the
    SCD2 tracked attribute is deterministic (no Faker/wall-clock). Sorted by IMO so
    the snapshot is byte-stable across runs.
    """
    imos = sorted(set(mapping.values()))
    return pd.DataFrame(
        {"imo": imos, "vessel_name": [f"Vessel {imo}" for imo in imos]}
    )


def _lanes_dataframe() -> pd.DataFrame:
    """Conformed dim_lane source: one row per directed international lane (lane_key)."""
    rows = [
        {"lane_key": f"{o}-{d}", "origin_unlocode": o, "dest_unlocode": d}
        for (o, d) in LANES
    ]
    return pd.DataFrame(rows, columns=["lane_key", "origin_unlocode", "dest_unlocode"])


def _read_synthetic_schedules(bucket: str) -> list[dict]:
    """Read the landed synthetic proforma schedules for the schedule_delta join.

    Returns the proforma rows (origin_unlocode, dest_unlocode, transit_days, ...) so
    derive_voyage_legs can join transit_hours vs proforma where a lane matches. An
    empty list (no schedules landed) yields all-None schedule_delta (Pitfall 8).
    """
    import json

    client = lib.gcs.get_client()
    gbucket = client.bucket(bucket)
    blobs = [
        b for b in client.list_blobs(gbucket, prefix="synthetic/schedules/")
        if b.name.endswith(".jsonl")
    ]
    rows: list[dict] = []
    for blob in sorted(blobs, key=lambda b: b.name):
        for raw in blob.download_as_bytes().splitlines():
            line = raw.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_silver(bucket: str) -> dict:
    """Run the full Bronze->Silver transform (no I/O writes); return frames + DQ counts.

    Pure orchestration of the landed Bronze inputs through identity -> geofence ->
    conform -> derive. Returns a dict with the four dim DataFrames, the two fact row
    lists, and the first-class DQ metrics (collision_count, dropped_mmsi_count,
    run_date, radius/min-dwell) the verify gates PRINT.
    """
    identity_rows, position_fixes = read_ais_fixes(bucket)

    # 1. MMSI->IMO resolution (D-04/D-05/D-06) + first-class DQ counts.
    mapping, collisions = identity.resolve_mmsi_to_imo(identity_rows)
    # WR-06: build the MMSI universe from REAL vessel MMSIs only. AIS rows with a
    # null/0/empty MMSI are non-vessel records, not "a MMSI seen in the slice" —
    # counting them inflates the no-IMO drop count (a deck-cited DQ metric, D-06).
    all_mmsis = [m for (m, _imo, _ts) in identity_rows if _is_real_mmsi(m)]
    dropped = identity.dropped_mmsi_count(all_mmsis, mapping)

    # Rekey position fixes by RESOLVED IMO; drop fixes whose MMSI never resolved (D-06).
    imo_fixes = [
        (mapping[mmsi], wkb, ts) for (mmsi, wkb, ts) in position_fixes if mmsi in mapping
    ]

    # Deterministic SCD2 anchor = the slice's max event date (never wall-clock, T-04-07).
    # WR-04: fail loud on an all-null/unparseable timestamp slice rather than
    # silently anchoring to a magic date — an AIS slice with zero parseable event
    # dates is a pipeline error, not a default.
    all_ts = [r[2] for r in identity_rows if r[2] is not None]
    if not all_ts:
        raise ValueError(
            "no parseable base_date_time in AIS slice — cannot anchor run_date (T-04-07)."
        )
    run_date = max(all_ts).date()

    centroids = port_centroids_from_bboxes()

    # 2. Geofence state machine -> port-call candidates (positions-only, D-02).
    calls = geofence.derive_port_calls(
        imo_fixes, centroids, radius_nm=RADIUS_NM, min_dwell_hours=MIN_DWELL_HOURS
    )

    # 3. Conform the four real dims.
    wpi = pd.DataFrame(
        {
            "unlocode": list(centroids.keys()),
            "lat": [centroids[c][0] for c in centroids],
            "lon": [centroids[c][1] for c in centroids],
        }
    )
    dim_port = conform.conform_dim_port(wpi)
    dim_lane = conform.conform_dim_lane(_lanes_dataframe())
    dim_vessel = conform.conform_dim_vessel(
        _vessel_snapshot_from_mapping(mapping), run_date=run_date
    )
    dim_carrier = conform.conform_dim_carrier(run_date=run_date)

    # 4. Derive both real facts (positions-only, D-02; per-fact dt= key, Pitfall 4).
    schedules = _read_synthetic_schedules(bucket)
    fact_port_call = derive.derive_fact_port_calls(calls, centroids)
    fact_voyage_leg = derive.derive_voyage_legs(calls, centroids, schedules=schedules)

    return {
        "dims": {
            "dim_port": dim_port,
            "dim_vessel": dim_vessel,
            "dim_carrier": dim_carrier,
            "dim_lane": dim_lane,
        },
        "facts": {
            "fact_port_call": fact_port_call,
            "fact_voyage_leg": fact_voyage_leg,
        },
        "dq": {
            "collision_count": collisions,
            "dropped_mmsi_count": dropped,
            "run_date": run_date.isoformat(),
            "radius_nm": RADIUS_NM,
            "min_dwell_hours": MIN_DWELL_HOURS,
            "resolved_vessels": len(set(mapping.values())),
        },
    }


def _land_dim(bucket: str, name: str, frame: pd.DataFrame, tmp: Path) -> bool:
    """Write a dim snapshot (no dt=) to local Parquet then upload_if_absent."""
    key = DIM_KEYS[name]
    local = tmp / name / Path(key).name
    local.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), local)
    return lib.gcs.upload_if_absent(bucket, key, str(local))


def _land_fact(bucket: str, name: str, rows: list[dict], date_field: str, tmp: Path) -> tuple[int, int]:
    """Partition fact rows by their per-record event date and upload_if_absent each.

    Returns ``(landed, skipped)``. Each partition lands one Parquet under
    ``<prefix>/dt=<event-date>/<name>.parquet`` (Pitfall 4 — never split a
    midnight-spanning fact; one explicit event-date column per fact).
    """
    prefix = FACT_PREFIXES[name]
    by_dt: dict[str, list[dict]] = {}
    for rec in rows:
        dt_part = _record_dt(rec, date_field, source=name)
        by_dt.setdefault(dt_part, []).append(rec)

    landed = 0
    skipped = 0
    for dt_part, recs in sorted(by_dt.items()):
        key = f"{prefix}/dt={dt_part}/{name}.parquet"
        local = tmp / name / f"dt={dt_part}" / f"{name}.parquet"
        local.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(recs)
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), local)
        if lib.gcs.upload_if_absent(bucket, key, str(local)):
            landed += 1
        else:
            skipped += 1
    return landed, skipped


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="silver.land_silver",
        description=(
            "Orchestrate the Bronze->Silver pipeline: read landed Bronze AIS + "
            "reference + synthetic, resolve MMSI->IMO, run the geofence state "
            "machine + conform the four real dims + derive the two real facts, and "
            "land the conformed Silver under gs://...-bronze/silver/ idempotently "
            "(write-once via upload_if_absent). Dims land as snapshots (no dt=); "
            "facts land under dt=YYYY-MM-DD/ keyed on each fact's event date (D-08)."
        ),
    )
    parser.add_argument(
        "--bucket",
        default=BRONZE_BUCKET_DEFAULT,
        help=f"Bronze/Silver bucket — accepts gs://name or bare name (default {BRONZE_BUCKET_DEFAULT}).",
    )
    parser.add_argument(
        "--step",
        choices=("conform", "derive", "all"),
        default="all",
        help="Which Silver objects to land: conform=dims only, derive=facts only, all=both (default all).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    bucket = _strip_gs(args.bucket)
    print(f"[INFO] land-silver: gs://{bucket}/silver/ (step={args.step}; write-once via upload_if_absent)")

    built = build_silver(bucket)
    dq = built["dq"]
    print(
        f"[INFO] silver transform: run_date={dq['run_date']} radius={dq['radius_nm']}nm "
        f"min_dwell={dq['min_dwell_hours']}hr resolved_vessels={dq['resolved_vessels']} "
        f"collisions={dq['collision_count']} dropped_mmsi={dq['dropped_mmsi_count']} "
        f"port_calls={len(built['facts']['fact_port_call'])} "
        f"voyage_legs={len(built['facts']['fact_voyage_leg'])}"
    )

    landed = 0
    skipped = 0
    with tempfile.TemporaryDirectory(prefix="ofa_land_silver_") as tmp:
        tmp_path = Path(tmp)

        if args.step in ("conform", "all"):
            for name in ("dim_carrier", "dim_lane", "dim_port", "dim_vessel"):
                if _land_dim(bucket, name, built["dims"][name], tmp_path):
                    landed += 1
                else:
                    skipped += 1

        if args.step in ("derive", "all"):
            for name, date_field in (("fact_port_call", "dt"), ("fact_voyage_leg", "dt")):
                f_landed, f_skipped = _land_fact(
                    bucket, name, built["facts"][name], date_field, tmp_path
                )
                landed += f_landed
                skipped += f_skipped

    print(
        f"[INFO] silver complete: {landed} landed, {skipped} skipped (write-once no-op) "
        f"across {landed + skipped} silver/ object(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
