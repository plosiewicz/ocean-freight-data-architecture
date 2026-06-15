"""Tests for the silver operated_by (vessel->carrier) bridge wiring (A3 / D-09).

The operated_by bridge gives UC1 carrier attribution its only source: AIS has no
operator field, so silver.conform.assign_operated_by reference-assigns each
resolved vessel IMO a carrier SCAC via a seeded numpy default_rng(SEED +
OPERATED_BY_OFFSET) (numpy pinned EXACT 1.26.4). This test guards:
  - byte-stable assignment across two calls (determinism),
  - every row provenance == "synthetic" (D-11),
  - every carrier_scac is a member of network.CARRIER_SCACS,
  - the column order is exactly [vessel_imo, carrier_scac, provenance],
  - build_silver wires the bridge in (the landing path includes operated_by).
"""

from __future__ import annotations

import pandas as pd

from data_gen import network
from silver import conform, land_silver


def test_assign_operated_by_byte_stable() -> None:
    a = conform.assign_operated_by(["9000001", "9000002"])
    b = conform.assign_operated_by(["9000001", "9000002"])
    pd.testing.assert_frame_equal(a, b), "operated_by must be byte-stable across runs"


def test_assign_operated_by_columns_and_provenance() -> None:
    df = conform.assign_operated_by(["9000001", "9000002", "9000003"])
    assert list(df.columns) == ["vessel_imo", "carrier_scac", "provenance"]
    assert (df["provenance"] == "synthetic").all()
    assert df["carrier_scac"].isin(set(network.CARRIER_SCACS)).all()
    assert list(df["vessel_imo"]) == ["9000001", "9000002", "9000003"]


def test_operated_by_wired_into_land_silver() -> None:
    """build_silver must produce an operated_by frame and main must land it under
    a silver/operated_by/ key (the wiring this plan adds)."""
    assert "operated_by" in land_silver.DIM_KEYS
    assert land_silver.DIM_KEYS["operated_by"].startswith("silver/operated_by/")
