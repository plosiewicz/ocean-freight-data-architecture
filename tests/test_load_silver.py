"""Unit tests for silver/land_silver.py Parquet type pinning — offline, no GCS.

These guard the BigQuery native-Parquet load type-mapping contract (T-05) that a
live `airflow dags test ofa_warehouse` run surfaced as two BQ 400 errors:

  1. fact_voyage_leg.schedule_delta must serialize as Parquet DOUBLE (FLOAT64),
     NOT INT32 — even when its populated values are all whole numbers, or the
     whole column is None (Pitfall 8, the real US->US slice with no matching
     synthetic proforma lane). pa.Table.from_pandas would otherwise INFER INT.
  2. fact_port_call.arrival_ts / departure_ts must serialize at MICROSECOND
     precision, NOT nanosecond — BigQuery TIMESTAMP rejects ns ("Invalid timestamp
     nanoseconds value"). pyarrow infers timestamp[ns] from Python datetimes.

The two transforms (silver.derive) are exercised end-to-end into the writer's
schema cast (silver.land_silver.silver_table) so the test mirrors exactly what
lands in gs://.../silver/ — an offline guard that would have caught both live
errors before the BQ load.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pyarrow as pa

from silver import derive
from silver.land_silver import SILVER_SCHEMAS, silver_table

CENTROIDS = {
    "USHOU": (29.75, -95.30),
    "USNYC": (40.70, -74.00),
    "USLAX": (33.74, -118.27),
}


def _call(imo: str, unlocode: str, arr: dt.datetime, dep: dt.datetime) -> dict:
    return {"imo": imo, "unlocode": unlocode, "arrival_ts": arr, "departure_ts": dep}


def test_voyage_leg_schedule_delta_is_float64_when_all_none() -> None:
    """All-None schedule_delta (no matching proforma lane) still lands as FLOAT64."""
    calls = [
        _call("9074729", "USHOU", dt.datetime(2024, 1, 1, 6, 0), dt.datetime(2024, 1, 1, 9, 0)),
        _call("9074729", "USNYC", dt.datetime(2024, 1, 4, 9, 0), dt.datetime(2024, 1, 4, 12, 0)),
    ]
    legs = derive.derive_voyage_legs(calls, CENTROIDS, schedules=None)
    assert legs and legs[0]["schedule_delta"] is None  # Pitfall 8 precondition
    table = silver_table("fact_voyage_leg", pd.DataFrame(legs))
    assert table.schema.field("schedule_delta").type == pa.float64()


def test_voyage_leg_schedule_delta_is_float64_when_whole_number() -> None:
    """A whole-number schedule_delta (8.0) lands as FLOAT64 (not inferred INT)."""
    schedules = [
        {"origin_unlocode": "USHOU", "dest_unlocode": "USLAX", "carrier_scac": "ABCD", "transit_days": 3}
    ]
    a_dep = dt.datetime(2024, 1, 1, 0, 0)
    b_arr = a_dep + dt.timedelta(hours=80)  # 80 - 72 = 8 (a whole number)
    calls = [
        _call("9074729", "USHOU", dt.datetime(2023, 12, 31, 21, 0), a_dep),
        _call("9074729", "USLAX", b_arr, b_arr + dt.timedelta(hours=3)),
    ]
    legs = derive.derive_voyage_legs(calls, CENTROIDS, schedules=schedules)
    assert abs(legs[0]["schedule_delta"] - 8.0) < 1e-9
    table = silver_table("fact_voyage_leg", pd.DataFrame(legs))
    assert table.schema.field("schedule_delta").type == pa.float64()


def test_voyage_leg_measures_and_keys_match_ddl_types() -> None:
    """transit_hours/distance_nm are FLOAT64 and dt is DATE (mirror sql/ddl_star.sql)."""
    calls = [
        _call("9074729", "USHOU", dt.datetime(2024, 1, 1, 6, 0), dt.datetime(2024, 1, 1, 9, 0)),
        _call("9074729", "USNYC", dt.datetime(2024, 1, 4, 9, 0), dt.datetime(2024, 1, 4, 12, 0)),
    ]
    legs = derive.derive_voyage_legs(calls, CENTROIDS)
    table = silver_table("fact_voyage_leg", pd.DataFrame(legs))
    assert table.schema.field("transit_hours").type == pa.float64()
    assert table.schema.field("distance_nm").type == pa.float64()
    assert table.schema.field("dt").type == pa.date32()


def test_port_call_timestamps_are_microsecond_not_nanosecond() -> None:
    """arrival_ts/departure_ts land as TIMESTAMP(us) — BQ rejects ns precision."""
    calls = [
        _call("9074729", "USHOU", dt.datetime(2024, 1, 1, 6, 0), dt.datetime(2024, 1, 1, 9, 0)),
    ]
    facts = derive.derive_fact_port_calls(calls, CENTROIDS)
    table = silver_table("fact_port_call", pd.DataFrame(facts))
    for col in ("arrival_ts", "departure_ts"):
        field_type = table.schema.field(col).type
        assert pa.types.is_timestamp(field_type)
        assert field_type.unit == "us", f"{col} must be microsecond, got {field_type.unit}"
    # dt partition is a DATE, lat/lon are FLOAT64.
    assert table.schema.field("dt").type == pa.date32()
    assert table.schema.field("lat").type == pa.float64()
    assert table.schema.field("lon").type == pa.float64()


def test_silver_table_round_trip_preserves_us_precision() -> None:
    """A datetime with sub-second precision truncates to us (never overflows as ns)."""
    calls = [
        _call(
            "9074729",
            "USHOU",
            dt.datetime(2024, 1, 1, 6, 0, 30, 123456),
            dt.datetime(2024, 1, 1, 9, 0, 0, 654321),
        ),
    ]
    facts = derive.derive_fact_port_calls(calls, CENTROIDS)
    table = silver_table("fact_port_call", pd.DataFrame(facts))
    arr = table.column("arrival_ts").to_pylist()[0]
    assert arr == dt.datetime(2024, 1, 1, 6, 0, 30, 123456)


def test_all_silver_schemas_have_no_nanosecond_timestamps() -> None:
    """No pinned Silver schema may declare a nanosecond timestamp (BQ-incompatible)."""
    for name, schema in SILVER_SCHEMAS.items():
        for field in schema:
            if pa.types.is_timestamp(field.type):
                assert field.type.unit == "us", (
                    f"{name}.{field.name} is timestamp[{field.type.unit}] — BQ TIMESTAMP "
                    "requires microsecond precision."
                )
