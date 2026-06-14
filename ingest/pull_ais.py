"""Land the bounded real AIS slice into GCS Bronze as source-format GeoParquet.

ING-02 / D-01..D-03, D-06, D-09. This module GETs MarineCadastre 2024 daily
GeoParquet files BY CONSTRUCTED FILENAME (the Azure container blocks anonymous
listing — Pitfall 1), filters at landing to the four US ports' bounding boxes +
cargo/tanker vessel types + a 5-minute cadence (D-06 downsample), and writes the
bounded slice — WKB geometry column preserved so Bronze stays genuinely
source-format GeoParquet (D-01) — under ``ais/dt=YYYY-MM-DD/`` idempotently.

The pure, network-free helpers (``wkb_point_lonlat`` / ``filter_vessel_type`` /
``filter_bbox`` / ``thin_5min``) are unit-tested in tests/test_pull_ais.py. The
fetch + land flow (Task 2) only runs under the ``__main__`` CLI.

Provenance: 03-RESEARCH.md § AIS Access Path RESOLVED / § Code Examples
"Land AIS GeoParquet with bbox/type/cadence filter"; Pitfall 1 + Pitfall 2.
Source data: Martin, Daniel R., et al. 2025. Nationwide Automatic Identification
System 2024. NOAA Office for Coastal Management (CC0 1.0).
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import struct
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

import lib.gcs

# --- Verified source path (NEVER list the container; GET by filename) ---
# 03-RESEARCH.md: live curl HTTP 200 + pyarrow schema read, 2026-06-14.
AZURE_BASE = "https://ocmgeodatastor1.blob.core.windows.net/marinecadastre/ais2024"

# --- Four-port bounding boxes (lon_min, lon_max, lat_min, lat_max) ---
# Houston/Galveston is RESEARCH-verified (lon -95.4..-94.0, lat 28.8..29.9).
# LA/Long Beach, NY/NJ, Savannah are defensible coastal boxes (Claude's discretion,
# A6 / D-04 four ports). Keyed by UN/LOCODE so they conform to dim_port in Phase 4.
PORT_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "USHOU": (-95.4, -94.0, 28.8, 29.9),   # Houston / Galveston (RESEARCH-verified)
    "USLAX": (-118.40, -118.10, 33.60, 33.80),  # LA / Long Beach (San Pedro Bay)
    "USNYC": (-74.25, -73.90, 40.50, 40.75),     # NY / NJ (Upper/Lower Bay, Newark Bay)
    "USSAV": (-81.15, -80.85, 31.95, 32.15),     # Savannah (Savannah River approach)
}

# Cargo (70-79) + tanker (80-89) vessel types (D-06).
VESSEL_TYPE_MIN = 70
VESSEL_TYPE_MAX = 89

# Column projection — read only what the filter + Phase-4 conformance need (cut I/O).
# Includes the WKB ``geometry`` column so the landed slice stays source-format GeoParquet.
READ_COLUMNS = ["mmsi", "base_date_time", "imo", "vessel_type", "cargo", "sog", "geometry"]

# 5-minute cadence bucket (D-06 downsample; data is already minute-rounded).
CADENCE_MINUTES = 5

# Default landing window: Q1 2024 (RESEARCH Open Question 1 — within D-02/D-05 envelope).
DEFAULT_START = "2024-01-01"
DEFAULT_END = "2024-03-31"

BRONZE_BUCKET_DEFAULT = "data-architecture-msds683-bronze"
LOCAL_CACHE_DEFAULT = Path("data/ais")

REQUEST_TIMEOUT_S = 300


# --------------------------------------------------------------------------- #
# Pure, network-free helpers (unit-tested)                                    #
# --------------------------------------------------------------------------- #
def wkb_point_lonlat(b: bytes) -> tuple[float, float]:
    """Decode a WKB Point's (lon, lat).

    Byte-order flag is at ``b[0]`` (1 = little-endian ``<``, else big-endian ``>``);
    the two doubles follow the 4-byte geometry-type code, at offsets [5:13] (lon/X)
    and [13:21] (lat/Y). Pure stdlib ``struct`` — avoids a shapely dependency
    (RESEARCH verified this decode against a real 2024 file).
    """
    fmt = "<" if b[0] == 1 else ">"
    lon = struct.unpack(fmt + "d", b[5:13])[0]
    lat = struct.unpack(fmt + "d", b[13:21])[0]
    return lon, lat


def filter_vessel_type(table: pa.Table) -> pa.Table:
    """Keep only cargo + tanker rows (vessel_type in 70..89)."""
    vt = table.column("vessel_type")
    mask = pc.and_(
        pc.greater_equal(vt, VESSEL_TYPE_MIN),
        pc.less_equal(vt, VESSEL_TYPE_MAX),
    )
    return table.filter(mask)


def filter_bbox(table: pa.Table, bbox: tuple[float, float, float, float]) -> pa.Table:
    """Keep rows whose WKB geometry decodes to a point inside ``bbox``.

    ``bbox`` is (lon_min, lon_max, lat_min, lat_max). Decodes the geometry column
    to lon/lat arrays once, then filters — O(rows), no per-row Python filter call.
    """
    lo_min, lo_max, la_min, la_max = bbox
    geoms = table.column("geometry").to_pylist()
    if not geoms:
        return table
    lons, lats = zip(*(wkb_point_lonlat(g) for g in geoms))
    lon_arr = pa.array(lons, type=pa.float64())
    lat_arr = pa.array(lats, type=pa.float64())
    mask = pc.and_(
        pc.and_(pc.greater_equal(lon_arr, lo_min), pc.less_equal(lon_arr, lo_max)),
        pc.and_(pc.greater_equal(lat_arr, la_min), pc.less_equal(lat_arr, la_max)),
    )
    return table.filter(mask)


def thin_5min(table: pa.Table) -> pa.Table:
    """Downsample to one row per (mmsi, 5-minute bucket) — deterministic.

    The source is already minute-rounded, so flooring ``base_date_time`` to a
    5-minute bucket and keeping the first row per (mmsi, bucket) yields a stable
    ~5x reduction (D-06). Deterministic: stable original row order is preserved by
    iterating indices in order and keeping the first occurrence per key.
    """
    if table.num_rows == 0:
        return table
    mmsis = table.column("mmsi").to_pylist()
    ts = table.column("base_date_time").to_pylist()
    seen: set[tuple[int, int]] = set()
    keep_indices: list[int] = []
    bucket_s = CADENCE_MINUTES * 60
    for i, (m, t) in enumerate(zip(mmsis, ts)):
        if t is None:
            bucket = -1
        else:
            # t is a datetime (pyarrow timestamp -> python datetime via to_pylist)
            epoch_s = int(t.timestamp()) if isinstance(t, dt.datetime) else int(t)
            bucket = epoch_s // bucket_s
        key = (m, bucket)
        if key in seen:
            continue
        seen.add(key)
        keep_indices.append(i)
    return table.take(pa.array(keep_indices, type=pa.int64()))


def filter_slice(table: pa.Table, bbox: tuple[float, float, float, float]) -> pa.Table:
    """Apply the full landing filter: vessel_type -> bbox -> 5-min cadence."""
    return thin_5min(filter_bbox(filter_vessel_type(table), bbox))


# --------------------------------------------------------------------------- #
# Fetch + land flow (Task 2 — only under the CLI)                             #
# --------------------------------------------------------------------------- #
def daily_filename(day: str) -> str:
    """Construct the verified daily GeoParquet filename for ``day`` (YYYY-MM-DD).

    Lowercase, hyphen-delimited: ``ais-2024-MM-DD.parquet`` (NEVER the CSV-fallback
    ``AIS_2024_MM_DD`` underscore form). The container is never listed (Pitfall 1).
    """
    return f"ais-{day}.parquet"


def day_url(day: str) -> str:
    """The full Azure blob URL for ``day``'s GeoParquet, by constructed filename."""
    return f"{AZURE_BASE}/{daily_filename(day)}"


def date_range(start: str, end: str) -> list[str]:
    """Inclusive list of ``YYYY-MM-DD`` strings from ``start`` to ``end``."""
    d0 = dt.date.fromisoformat(start)
    d1 = dt.date.fromisoformat(end)
    if d1 < d0:
        raise ValueError(f"end {end} precedes start {start}")
    days: list[str] = []
    d = d0
    while d <= d1:
        days.append(d.isoformat())
        d += dt.timedelta(days=1)
    return days


def validate_remote_schema(table: pa.Table) -> None:
    """Fail loud on the CSV-fallback (PascalCase) schema rather than mislanding.

    The 2024 GeoParquet uses lowercase snake_case + a WKB ``geometry`` column. The
    NOAA CSV fallback uses ``MMSI``/``LAT``/``LON``/``VesselType`` (PascalCase, no
    geometry). If the projected read did not yield the GeoParquet columns, the
    source shape is wrong — refuse to land (Pitfall 2 / threat T-03-04, V5 input
    validation).
    """
    names = set(table.column_names)
    required = {"mmsi", "vessel_type", "geometry"}
    missing = required - names
    if missing:
        raise RuntimeError(
            "remote AIS file does not look like 2024 GeoParquet "
            f"(missing {sorted(missing)}; got {sorted(names)}). "
            "Refusing to land — this may be the CSV fallback schema (D-03/Pitfall 2)."
        )


def fetch_day_table(day: str, *, session: requests.Session | None = None) -> pa.Table:
    """GET ``day``'s GeoParquet by constructed filename; return the projected table.

    Validates the remote schema before any downstream use (fail-loud, T-03-04).
    Never lists the container — GETs the exact filename only (Pitfall 1).
    """
    getter = session.get if session is not None else requests.get
    resp = getter(day_url(day), timeout=REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    table = pq.read_table(io.BytesIO(resp.content), columns=READ_COLUMNS)
    validate_remote_schema(table)
    return table


def probe_first_day(day: str, *, session: requests.Session | None = None) -> None:
    """HTTP-probe the first day's GeoParquet, expecting 200, before landing.

    Fails loud with the D-03 CSV-fallback note if the day's GeoParquet is missing,
    so we never silently land a partial / wrong-shape window.
    """
    getter = session.get if session is not None else requests.get
    resp = getter(day_url(day), stream=True, timeout=REQUEST_TIMEOUT_S)
    if resp.status_code != 200:
        raise RuntimeError(
            f"AIS GeoParquet probe failed for {day}: HTTP {resp.status_code} at "
            f"{day_url(day)}. D-03 fallback: the NOAA CSV-zip path "
            f"(coast.noaa.gov/.../AIS_{day.replace('-', '_')}.zip) is the documented "
            "convert-at-landing fallback — re-run with a different quarter or wire "
            "the fallback before proceeding."
        )
    resp.close()


def land_day(
    day: str,
    *,
    bucket: str,
    cache_dir: Path,
    session: requests.Session | None = None,
) -> tuple[bool, int]:
    """Fetch -> filter -> write local GeoParquet -> idempotent Bronze upload.

    Returns ``(uploaded, filtered_rows)``. Re-running no-ops on already-landed days
    (upload_if_absent, D-06/D-09). The WKB geometry column is preserved in the
    written file so Bronze stays source-format GeoParquet (D-01).
    """
    key = f"ais/dt={day}/ais-{day}.parquet"
    table = fetch_day_table(day, session=session)

    filtered = pa.concat_tables(
        [filter_slice(table, bbox) for bbox in PORT_BBOXES.values()]
    )

    day_dir = cache_dir / f"dt={day}"
    day_dir.mkdir(parents=True, exist_ok=True)
    local_path = day_dir / f"ais-{day}.parquet"
    pq.write_table(filtered, local_path)

    uploaded = lib.gcs.upload_if_absent(bucket, key, str(local_path))
    return uploaded, filtered.num_rows


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ingest.pull_ais",
        description=(
            "Land the bounded real AIS slice (4 US ports, one 2024 quarter) into "
            "GCS Bronze as source-format GeoParquet. GETs daily files by constructed "
            "filename (never lists the Azure container) and lands idempotently."
        ),
    )
    parser.add_argument("--start", default=DEFAULT_START, help="First day, YYYY-MM-DD (default Q1 2024 start).")
    parser.add_argument("--end", default=DEFAULT_END, help="Last day, YYYY-MM-DD (default Q1 2024 end).")
    parser.add_argument(
        "--bucket",
        default=BRONZE_BUCKET_DEFAULT,
        help=f"Bronze bucket name (default {BRONZE_BUCKET_DEFAULT}).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=LOCAL_CACHE_DEFAULT,
        help=f"Local staging dir for fetched/filtered parquet (default {LOCAL_CACHE_DEFAULT}; gitignored).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    days = date_range(args.start, args.end)
    print(f"[INFO] pull-ais: {len(days)} days {args.start}..{args.end} -> gs://{args.bucket}/ais/")

    session = requests.Session()
    # Pin the window: probe the first day before committing to it (D-03 fallback note).
    probe_first_day(days[0], session=session)

    landed = 0
    skipped = 0
    total_rows = 0
    for day in days:
        try:
            uploaded, rows = land_day(
                day, bucket=args.bucket, cache_dir=args.cache_dir, session=session
            )
        except requests.HTTPError as exc:  # missing day -> fail loud with D-03 note
            print(
                f"[FAIL] {day}: {exc} — D-03 fallback is the NOAA CSV-zip path "
                f"(AIS_{day.replace('-', '_')}.zip).",
                file=sys.stderr,
            )
            return 2
        total_rows += rows
        if uploaded:
            landed += 1
            print(f"[OK] {day}: landed {rows} filtered rows")
        else:
            skipped += 1
            print(f"[SKIP] {day}: already landed (write-once no-op)")

    print(
        f"[INFO] pull-ais complete: {landed} landed, {skipped} skipped, "
        f"{total_rows} total filtered rows across {len(days)} days. "
        "(Exact citable rows/bytes asserted by the AIS verify gate, plan 03-05.)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
