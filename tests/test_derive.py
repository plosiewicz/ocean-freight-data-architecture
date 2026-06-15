"""Unit tests for silver/derive.py — pure fact derivation, no network/GCS.

Covers the behaviors specified in 04-04-PLAN.md Task 1 (ETL-01 / criterion 2):
  - fact_port_call rows carry the conformed UN/LOCODE (not AIS destination text),
    the port centroid lat/lon, and provenance="real" (D-02 / D-11).
  - fact_voyage_leg pairs each vessel's consecutive calls (A->B): one leg with
    transit_hours = B.arrival - A.departure, distance_nm = great-circle between
    centroids, provenance="real" (D-10).
  - a single-call vessel produces ZERO legs (Pitfall 7).
  - two consecutive calls at the SAME port produce a leg with distance_nm == 0
    (kept + counted per the documented policy, Pitfall 7).
  - schedule_delta is NaN/None for a leg whose (origin,dest) has no matching
    synthetic proforma lane (Pitfall 8); it is populated only on a matched lane.

All inputs are tiny hand-built call lists + a small synthetic schedule fixture;
no Bronze read, no GCS, no creds.
"""

from __future__ import annotations

import datetime as dt
import math

from silver import derive
from silver.haversine import haversine_nm

# Centroids for the test ports (decimal degrees, US West-negative longitude).
# USHOU ~ Houston, USNYC ~ New York, USLAX ~ Los Angeles.
CENTROIDS = {
    "USHOU": (29.75, -95.30),
    "USNYC": (40.70, -74.00),
    "USLAX": (33.74, -118.27),
}


def _call(imo: str, unlocode: str, arr: dt.datetime, dep: dt.datetime) -> dict:
    """Geofence-shaped call dict (matches silver.geofence.derive_port_calls)."""
    return {
        "imo": imo,
        "unlocode": unlocode,
        "arrival_ts": arr,
        "departure_ts": dep,
    }


def test_port_calls_carry_conformed_code_centroid_and_provenance() -> None:
    """fact_port_call rows attach centroid lat/lon + provenance='real' (D-02/D-11)."""
    calls = [
        _call(
            "9074729",
            "USHOU",
            dt.datetime(2024, 1, 1, 6, 0),
            dt.datetime(2024, 1, 1, 9, 0),
        )
    ]
    facts = derive.derive_fact_port_calls(calls, CENTROIDS)
    assert len(facts) == 1
    row = facts[0]
    assert row["unlocode"] == "USHOU"
    assert "destination" not in row  # D-02: no AIS free-text destination column
    assert abs(row["lat"] - 29.75) < 1e-9
    assert abs(row["lon"] - (-95.30)) < 1e-9
    assert row["provenance"] == "real"
    # partition date = arrival date (Pitfall 4).
    assert row["dt"] == dt.date(2024, 1, 1)


def test_two_call_vessel_yields_one_leg_with_transit_and_distance() -> None:
    """A vessel with calls A then B yields one leg A->B (D-10)."""
    a_dep = dt.datetime(2024, 1, 1, 9, 0)
    b_arr = dt.datetime(2024, 1, 4, 9, 0)  # 72 hours after A departure
    calls = [
        _call("9074729", "USHOU", dt.datetime(2024, 1, 1, 6, 0), a_dep),
        _call("9074729", "USNYC", b_arr, dt.datetime(2024, 1, 4, 12, 0)),
    ]
    legs = derive.derive_voyage_legs(calls, CENTROIDS)
    assert len(legs) == 1
    leg = legs[0]
    assert leg["vessel_imo"] == "9074729"
    assert leg["origin_unlocode"] == "USHOU"
    assert leg["dest_unlocode"] == "USNYC"
    assert abs(leg["transit_hours"] - 72.0) < 1e-9
    expected_nm = haversine_nm(29.75, -95.30, 40.70, -74.00)
    assert abs(leg["distance_nm"] - expected_nm) < 1e-6
    assert leg["provenance"] == "real"
    # partition date = origin-departure date (Pitfall 4).
    assert leg["dt"] == dt.date(2024, 1, 1)


def test_single_call_vessel_yields_zero_legs() -> None:
    """A vessel with exactly ONE call produces ZERO legs (Pitfall 7)."""
    calls = [
        _call(
            "9074729",
            "USHOU",
            dt.datetime(2024, 1, 1, 6, 0),
            dt.datetime(2024, 1, 1, 9, 0),
        )
    ]
    legs = derive.derive_voyage_legs(calls, CENTROIDS)
    assert legs == []


def test_same_port_consecutive_calls_yield_zero_distance_leg() -> None:
    """Two consecutive calls at the SAME port -> distance_nm == 0, kept (Pitfall 7)."""
    calls = [
        _call("9074729", "USHOU", dt.datetime(2024, 1, 1, 6, 0), dt.datetime(2024, 1, 1, 9, 0)),
        _call("9074729", "USHOU", dt.datetime(2024, 1, 2, 6, 0), dt.datetime(2024, 1, 2, 9, 0)),
    ]
    legs = derive.derive_voyage_legs(calls, CENTROIDS)
    assert len(legs) == 1
    assert legs[0]["origin_unlocode"] == "USHOU"
    assert legs[0]["dest_unlocode"] == "USHOU"
    assert legs[0]["distance_nm"] == 0.0


def test_schedule_delta_nan_on_unmatched_lane() -> None:
    """schedule_delta is NaN for a leg with no matching synthetic proforma (Pitfall 8)."""
    # Synthetic proforma covers only USHOU->USLAX, NOT USHOU->USNYC.
    schedules = [
        {
            "origin_unlocode": "USHOU",
            "dest_unlocode": "USLAX",
            "carrier_scac": "ABCD",
            "transit_days": 3,
        }
    ]
    # Real leg USHOU->USNYC: no matching proforma lane -> schedule_delta NaN.
    calls = [
        _call("9074729", "USHOU", dt.datetime(2024, 1, 1, 6, 0), dt.datetime(2024, 1, 1, 9, 0)),
        _call("9074729", "USNYC", dt.datetime(2024, 1, 4, 9, 0), dt.datetime(2024, 1, 4, 12, 0)),
    ]
    legs = derive.derive_voyage_legs(calls, CENTROIDS, schedules=schedules)
    assert len(legs) == 1
    assert legs[0]["schedule_delta"] is None or math.isnan(legs[0]["schedule_delta"])


def test_schedule_delta_populated_on_matched_lane() -> None:
    """schedule_delta = transit_hours - (proforma transit_days * 24) on a matched lane."""
    schedules = [
        {
            "origin_unlocode": "USHOU",
            "dest_unlocode": "USLAX",
            "carrier_scac": "ABCD",
            "transit_days": 3,  # proforma transit_hours = 72
        }
    ]
    # Real leg USHOU->USLAX taking 80 hours -> schedule_delta = 80 - 72 = 8.
    a_dep = dt.datetime(2024, 1, 1, 0, 0)
    b_arr = a_dep + dt.timedelta(hours=80)
    calls = [
        _call("9074729", "USHOU", dt.datetime(2023, 12, 31, 21, 0), a_dep),
        _call("9074729", "USLAX", b_arr, b_arr + dt.timedelta(hours=3)),
    ]
    legs = derive.derive_voyage_legs(calls, CENTROIDS, schedules=schedules)
    assert len(legs) == 1
    assert legs[0]["schedule_delta"] is not None
    assert abs(legs[0]["schedule_delta"] - 8.0) < 1e-9
