"""RED-then-GREEN tests for data_gen.conditioning (ING-04, A2).

The conditioning turns the three real priors landed in Bronze (LSCI, Comtrade
O-D, LPI) into the WEIGHTS/MEANS that make the synthetic network plausible —
never into facts (D-13). These tests pin the defensible math:

  - lane_weight(A, B) = norm(LSCI[ctry A]) x norm(LSCI[ctry B])
                        x norm(ComtradeOD[ctry A -> ctry B])
    is finite, non-negative, and a higher-LSCI/higher-trade lane outranks a
    lower one (A2).
  - country_delay_params(country) is monotonic in LPI — a higher LPI yields a
    lower expected delay — and feeds a seeded numpy distribution mean.

Small in-test fixture priors keep the run network-free and <1s.
"""

from __future__ import annotations

import math

import pytest

from data_gen import conditioning


# --- Fixture priors (tiny, in-memory; no Bronze / no network) --------------- #
# Two countries: GOOD (high LSCI, high trade, high LPI) vs POOR (low all).
FIXTURE_LSCI = {"GOOD": 90.0, "POOR": 10.0, "MID": 50.0}
# Comtrade O-D matrix: (reporter_iso3, partner_iso3) -> trade value.
FIXTURE_COMTRADE = {
    ("GOOD", "GOOD"): 1_000_000.0,
    ("GOOD", "POOR"): 10_000.0,
    ("POOR", "POOR"): 5_000.0,
    ("MID", "MID"): 100_000.0,
}
# LPI 1..5 (higher = more reliable -> lower delay).
FIXTURE_LPI = {"GOOD": 4.5, "POOR": 2.0, "MID": 3.2}

# Two fixture ports per country so lane_weight gets a port->country mapping.
FIXTURE_PORTS = {
    "PGOOD": "GOOD",
    "PPOOR": "POOR",
    "PMID": "MID",
}


@pytest.fixture
def cond() -> conditioning.Conditioner:
    return conditioning.Conditioner(
        lsci_by_country=FIXTURE_LSCI,
        comtrade_od=FIXTURE_COMTRADE,
        lpi_by_country=FIXTURE_LPI,
        port_country=FIXTURE_PORTS,
    )


def test_lane_weights(cond: conditioning.Conditioner) -> None:
    """lane_weight is finite, non-negative, and higher-trade outranks lower."""
    w_good = cond.lane_weight("PGOOD", "PGOOD")  # high LSCI x high LSCI x high trade
    w_poor = cond.lane_weight("PPOOR", "PPOOR")  # low LSCI x low LSCI x low trade

    for w in (w_good, w_poor):
        assert math.isfinite(w), "lane_weight must be finite (A2 normalization)"
        assert w >= 0.0, "lane_weight must be non-negative"

    assert w_good > w_poor, "higher-LSCI/higher-trade lane must outrank a lower one"


def test_lane_weight_zero_when_no_trade(cond: conditioning.Conditioner) -> None:
    """An O-D pair absent from Comtrade contributes a zero trade factor."""
    # (POOR, GOOD) is not in FIXTURE_COMTRADE -> trade factor 0 -> weight 0.
    assert cond.lane_weight("PPOOR", "PGOOD") == 0.0


def test_lane_weight_normalization_finite_on_degenerate() -> None:
    """Degenerate (single-value) priors must not divide-by-zero (A2)."""
    cond = conditioning.Conditioner(
        lsci_by_country={"X": 42.0},
        comtrade_od={("X", "X"): 7.0},
        lpi_by_country={"X": 3.0},
        port_country={"PX": "X"},
    )
    w = cond.lane_weight("PX", "PX")
    assert math.isfinite(w) and w >= 0.0


def test_delay_distribution(cond: conditioning.Conditioner) -> None:
    """expected_delay is monotonic-decreasing in LPI (higher LPI -> less delay)."""
    good = cond.country_delay_params("GOOD")  # LPI 4.5
    poor = cond.country_delay_params("POOR")  # LPI 2.0

    assert good["mean_hours"] >= 0.0 and poor["mean_hours"] >= 0.0
    assert math.isfinite(good["mean_hours"]) and math.isfinite(poor["mean_hours"])
    assert poor["mean_hours"] > good["mean_hours"], (
        "lower LPI must map to a higher expected delay (monotonic in LPI)"
    )


def test_delay_params_feed_seeded_numpy(cond: conditioning.Conditioner) -> None:
    """The mean feeds a SEEDED numpy draw — identical seed -> identical draw."""
    params = cond.country_delay_params("MID")
    a = cond.draw_delay_hours("MID", seed=123)
    b = cond.draw_delay_hours("MID", seed=123)
    assert a == b, "seeded delay draw must be deterministic"
    assert a >= 0.0 and math.isfinite(a)
    # The draw is centered on (not equal to) the distribution mean.
    assert params["mean_hours"] > 0.0


def test_unknown_country_delay_fails_loud(cond: conditioning.Conditioner) -> None:
    """A country with no LPI prior must fail loud, not silently fabricate."""
    with pytest.raises(KeyError):
        cond.country_delay_params("ATLANTIS")
