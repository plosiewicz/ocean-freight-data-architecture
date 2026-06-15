"""Unit tests for the pure great-circle distance helper — no network, no GCS.

Covers the three behaviors specified in 04-01-PLAN.md Task 1:
  - identical points -> zero distance
  - a known great-circle pair (~1 degree of latitude ~= 60 nm) within tolerance
  - distance is symmetric: haversine_nm(a, b) == haversine_nm(b, a)

All inputs are plain floats; no cloud, credentials, or I/O are touched here.
"""

from __future__ import annotations

from silver.haversine import haversine_nm


def test_identical_points_zero_distance() -> None:
    """Identical lat/lon pairs return exactly 0.0 great-circle distance."""
    assert haversine_nm(0.0, 0.0, 0.0, 0.0) == 0.0
    assert haversine_nm(29.0, -95.0, 29.0, -95.0) == 0.0


def test_known_one_degree_latitude_is_about_sixty_nm() -> None:
    """One degree of latitude is ~60 nautical miles (a great-circle fixture)."""
    # 0,0 -> 1,0 spans one degree of latitude; 1 deg ~= 60 nm by definition of nm.
    nm = haversine_nm(0.0, 0.0, 1.0, 0.0)
    assert abs(nm - 60.0) < 0.5


def test_symmetric() -> None:
    """haversine_nm is symmetric in its two endpoints."""
    a_lat, a_lon = 29.75, -95.20   # Houston-ish
    b_lat, b_lon = 33.74, -118.27  # LA/Long Beach-ish
    fwd = haversine_nm(a_lat, a_lon, b_lat, b_lon)
    rev = haversine_nm(b_lat, b_lon, a_lat, a_lon)
    assert abs(fwd - rev) < 1e-9
