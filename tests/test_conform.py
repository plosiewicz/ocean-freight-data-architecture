"""Unit tests for silver/conform.py — pure conformance transforms, no network/GCS.

Covers the six behaviors specified in 04-03-PLAN.md Task 1 (ETL-01 / criteria 1+4
/ D-09/D-11), all on tiny hand-built DataFrames (Pattern 1 pure-transform split):
  - assign_surrogate sorts by the natural key and assigns 1-based INT64 surrogate
    keys; re-running yields the identical surrogate->natural mapping (determinism).
  - SCD1 conformance (dim_port / dim_lane) -> current snapshot, no history columns;
    each row carries a conformed natural key + surrogate + provenance.
  - SCD2 conformance (dim_vessel / dim_carrier) -> a second snapshot where a tracked
    attribute changed for one natural key closes the old row (is_current=False,
    effective_to=run_date) and appends a new current row; row_hash differs.
  - SCD2 effective_from is anchored to a passed-in run_date (NOT datetime.now):
    same run_date in -> same effective_from out (determinism).
  - every conformed row carries provenance in {real, synthetic} (D-11).
  - the WPI centroid sanity assertion raises (fail loud) if a target port's
    centroid falls OUTSIDE its PORT_BBOXES box (Pitfall 6).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from silver import conform

RUN_DATE = dt.date(2024, 1, 7)  # slice max event date — the SCD2 anchor.

# Two valid IMOs (pass the IMO check digit): 9074729 (golden) and 9000015.
IMO_A = "9074729"
IMO_B = "9000015"


def test_assign_surrogate_deterministic_and_int64() -> None:
    """1-based INT64 surrogate by sorted natural key; stable across re-runs."""
    df = pd.DataFrame({"unlocode": ["USNYC", "USHOU", "USLAX"]})
    out1 = conform.assign_surrogate(df, "unlocode")
    out2 = conform.assign_surrogate(df, "unlocode")

    # Sorted by natural key -> 1-based surrogate assignment.
    mapping = dict(zip(out1["unlocode"], out1["surrogate_key"]))
    assert mapping == {"USHOU": 1, "USLAX": 2, "USNYC": 3}
    assert str(out1["surrogate_key"].dtype) == "int64"
    # Determinism: identical surrogate->natural mapping on a re-run.
    assert dict(zip(out2["unlocode"], out2["surrogate_key"])) == mapping


def test_scd1_port_snapshot_has_no_history_columns() -> None:
    """dim_port SCD1 = current snapshot, surrogate + natural key + provenance, no SCD2 cols."""
    wpi = pd.DataFrame(
        {
            "unlocode": ["USHOU", "USLAX"],
            "lat": [29.35, 33.70],
            "lon": [-95.0, -118.25],
        }
    )
    dim = conform.conform_dim_port(wpi)
    assert "surrogate_key" in dim.columns
    assert "unlocode" in dim.columns
    assert "provenance" in dim.columns
    # SCD1 = no history columns.
    for col in ("effective_from", "effective_to", "is_current", "row_hash"):
        assert col not in dim.columns
    # Real reference dim.
    assert set(dim["provenance"]) == {"real"}


def test_scd1_lane_snapshot_has_no_history_columns() -> None:
    lanes = pd.DataFrame({"lane_key": ["USHOU-USLAX", "USNYC-USSAV"]})
    dim = conform.conform_dim_lane(lanes)
    assert "surrogate_key" in dim.columns
    assert "lane_key" in dim.columns
    assert set(dim["provenance"]) == {"real"}
    for col in ("effective_from", "effective_to", "is_current", "row_hash"):
        assert col not in dim.columns


def test_scd2_two_snapshot_versioning_closes_old_opens_new() -> None:
    """A changed tracked attr closes the old row and opens a new current row."""
    snap1 = pd.DataFrame({"imo": [IMO_A], "vessel_name": ["EVER GIVEN"]})
    snap2 = pd.DataFrame({"imo": [IMO_A], "vessel_name": ["EVER FORWARD"]})  # renamed

    dim1 = conform.conform_dim_vessel(snap1, run_date=RUN_DATE)
    assert len(dim1) == 1
    assert bool(dim1.iloc[0]["is_current"]) is True

    dim2 = conform.conform_dim_vessel(snap2, run_date=RUN_DATE, existing=dim1)
    # Old row closed, new current row appended -> two versions for the same IMO.
    versions = dim2[dim2["imo"] == IMO_A]
    assert len(versions) == 2
    closed = versions[versions["is_current"] == False]  # noqa: E712
    current = versions[versions["is_current"] == True]  # noqa: E712
    assert len(closed) == 1 and len(current) == 1
    # Closed row's effective_to is the run_date.
    assert closed.iloc[0]["effective_to"] == RUN_DATE
    # row_hash differs between the two versions (change detected).
    assert closed.iloc[0]["row_hash"] != current.iloc[0]["row_hash"]


def test_scd2_no_change_keeps_single_current_row() -> None:
    """Reloading an unchanged snapshot does NOT version (idempotent reload)."""
    snap = pd.DataFrame({"imo": [IMO_A], "vessel_name": ["EVER GIVEN"]})
    dim1 = conform.conform_dim_vessel(snap, run_date=RUN_DATE)
    dim2 = conform.conform_dim_vessel(snap, run_date=RUN_DATE, existing=dim1)
    versions = dim2[dim2["imo"] == IMO_A]
    assert len(versions) == 1
    assert bool(versions.iloc[0]["is_current"]) is True


def test_scd2_effective_from_uses_run_date_not_wallclock() -> None:
    """Same run_date in -> same effective_from out (no datetime.now)."""
    snap = pd.DataFrame({"imo": [IMO_A], "vessel_name": ["EVER GIVEN"]})
    a = conform.conform_dim_vessel(snap, run_date=RUN_DATE)
    b = conform.conform_dim_vessel(snap, run_date=RUN_DATE)
    assert a.iloc[0]["effective_from"] == RUN_DATE
    assert a.iloc[0]["effective_from"] == b.iloc[0]["effective_from"]


def test_scd2_carrier_provenance_is_synthetic() -> None:
    """dim_carrier (reference-assigned) carries provenance='synthetic' (D-09/D-11)."""
    dim = conform.conform_dim_carrier(run_date=RUN_DATE)
    assert len(dim) > 0
    assert set(dim["provenance"]) == {"synthetic"}
    assert "scac" in dim.columns
    assert "surrogate_key" in dim.columns
    for col in ("effective_from", "effective_to", "is_current", "row_hash"):
        assert col in dim.columns


def test_operated_by_assignment_deterministic_and_synthetic() -> None:
    """Seeded vessel->carrier assignment is deterministic and synthetic-tagged."""
    imos = [IMO_A, IMO_B]
    a = conform.assign_operated_by(imos)
    b = conform.assign_operated_by(imos)
    # Determinism: identical assignment across runs (seeded RNG).
    assert a.to_dict("records") == b.to_dict("records")
    assert set(a["provenance"]) == {"synthetic"}
    assert set(a["vessel_imo"]) == set(imos)


def test_every_conformed_row_has_valid_provenance() -> None:
    """D-11: provenance in {real, synthetic} on every conformed row across dims."""
    wpi = pd.DataFrame({"unlocode": ["USHOU"], "lat": [29.35], "lon": [-95.0]})
    port = conform.conform_dim_port(wpi)
    vessel = conform.conform_dim_vessel(
        pd.DataFrame({"imo": [IMO_A], "vessel_name": ["X"]}), run_date=RUN_DATE
    )
    carrier = conform.conform_dim_carrier(run_date=RUN_DATE)
    for dim in (port, vessel, carrier):
        assert set(dim["provenance"]).issubset({"real", "synthetic"})
        assert dim["provenance"].notna().all()


def test_centroid_sanity_passes_for_in_bbox_centroids() -> None:
    """Centroids inside their PORT_BBOXES boxes pass the sanity assertion."""
    wpi = pd.DataFrame(
        {
            "unlocode": ["USHOU", "USLAX", "USNYC", "USSAV"],
            "lat": [29.35, 33.70, 40.65, 32.05],
            "lon": [-95.0, -118.25, -74.05, -81.0],
        }
    )
    # Must not raise.
    conform.assert_centroids_in_bbox(wpi)


def test_centroid_sanity_raises_for_out_of_bbox_centroid() -> None:
    """A target port centroid OUTSIDE its bbox fails loud with the port code (Pitfall 6)."""
    wpi = pd.DataFrame(
        {
            "unlocode": ["USHOU"],
            # Positive longitude (sign error) -> wrong hemisphere, outside the bbox.
            "lat": [29.35],
            "lon": [95.0],
        }
    )
    with pytest.raises(ValueError, match="USHOU"):
        conform.assert_centroids_in_bbox(wpi)
