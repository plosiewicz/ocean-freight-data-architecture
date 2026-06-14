"""Unit tests for the pure AIS landing helpers — no network, no GCS, no Azure.

Covers the three behaviors specified in 03-02-PLAN.md Task 1:
  - WKB Point decode (both byte orders) -> (lon, lat)
  - vessel_type filter keeps only cargo+tanker (70..89)
  - bbox filter drops out-of-box points, keeps in-box points

All inputs are tiny hand-built pyarrow tables and known WKB byte strings; the
Azure endpoint is NEVER touched here (Pitfall 1 / threat T-03-04).
"""

from __future__ import annotations

import struct

import pyarrow as pa

from ingest import pull_ais


def _wkb_point(lon: float, lat: float, little_endian: bool = True) -> bytes:
    """Build a WKB Point: byte-order flag + geom-type(1=Point) + lon + lat."""
    if little_endian:
        return struct.pack("<B", 1) + struct.pack("<I", 1) + struct.pack("<d", lon) + struct.pack("<d", lat)
    return struct.pack(">B", 0) + struct.pack(">I", 1) + struct.pack(">d", lon) + struct.pack(">d", lat)


# Houston/Galveston bbox is RESEARCH-verified (lon -95.4..-94.0, lat 28.8..29.9).
HOUSTON = pull_ais.PORT_BBOXES["USHOU"]


def test_wkb_point_lonlat() -> None:
    """Decoding a known Point WKB returns (lon, lat); both byte orders handled."""
    lon, lat = -95.0, 29.0

    le_lon, le_lat = pull_ais.wkb_point_lonlat(_wkb_point(lon, lat, little_endian=True))
    assert abs(le_lon - lon) < 1e-9
    assert abs(le_lat - lat) < 1e-9

    be_lon, be_lat = pull_ais.wkb_point_lonlat(_wkb_point(lon, lat, little_endian=False))
    assert abs(be_lon - lon) < 1e-9
    assert abs(be_lat - lat) < 1e-9


def test_vessel_type_filter() -> None:
    """Only vessel_type in 70..89 (cargo + tanker) survives the filter."""
    # geometry values must be valid WKB so the bbox decode does not blow up later,
    # but this test isolates the vessel_type predicate via filter_vessel_type.
    table = pa.table(
        {
            "mmsi": [1, 2, 3, 4, 5],
            "vessel_type": [70, 89, 69, 90, 80],  # keep 70, 89, 80 ; drop 69, 90
            "geometry": [_wkb_point(-95.0, 29.0)] * 5,
        }
    )
    out = pull_ais.filter_vessel_type(table)
    assert out.column("vessel_type").to_pylist() == [70, 89, 80]
    assert out.column("mmsi").to_pylist() == [1, 2, 5]


def test_bbox_filter() -> None:
    """Points outside the Houston bbox are dropped; in-box points are kept."""
    lo_min, lo_max, la_min, la_max = HOUSTON
    inside_lon = (lo_min + lo_max) / 2.0
    inside_lat = (la_min + la_max) / 2.0
    table = pa.table(
        {
            "mmsi": [10, 11, 12, 13],
            "vessel_type": [70, 70, 70, 70],
            "geometry": [
                _wkb_point(inside_lon, inside_lat),  # inside -> keep
                _wkb_point(lo_min - 1.0, inside_lat),  # west of box -> drop
                _wkb_point(inside_lon, la_max + 1.0),  # north of box -> drop
                _wkb_point(lo_max + 0.01, inside_lat),  # just east -> drop
            ],
        }
    )
    out = pull_ais.filter_bbox(table, HOUSTON)
    assert out.column("mmsi").to_pylist() == [10]
