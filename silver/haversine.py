"""Great-circle distance in nautical miles — hand-rolled, stdlib ``math`` only.

ETL-01. The single pure-math primitive every Silver geofence / voyage-leg
computation builds on: ``haversine_nm(lat1, lon1, lat2, lon2)`` returns the
great-circle distance between two WGS84 lat/lon points in nautical miles.

Hand-rolled deliberately — the project pins a minimal stack and 04-RESEARCH.md
§ Don't Hand-Roll forbids adding ``geopy`` / ``pyproj`` / ``shapely`` / the
``haversine`` package for ~10 lines of math (haversine-vs-WGS84-geodesic error
is <0.5%, negligible for ``distance_nm`` on a course deliverable).

Provenance: 04-RESEARCH.md § Architecture Patterns Pattern 2 (verbatim formula +
``EARTH_RADIUS_NM = 3440.065``); geofence-around-port convention cited from
ScienceDirect S0029801824001082 ("Port call extraction from vessel location
data for characterising harbour traffic").
"""

from __future__ import annotations

import math

EARTH_RADIUS_NM = 3440.065  # mean Earth radius in nautical miles


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))
