from __future__ import annotations

from analytics import route_reliability


BASELINE = [
    {"port": "USNYC", "leg_hours": 0},
    {"port": "CNSHA", "leg_hours": 355.97},
]
REROUTE = [
    {"port": "USNYC", "leg_hours": 0},
    {"port": "USLAX", "leg_hours": 118.4},
    {"port": "CNSHA", "leg_hours": 313.79},
]


def test_route_reliability_golden_path_pins() -> None:
    baseline = route_reliability.route_reliability(BASELINE)
    reroute = route_reliability.route_reliability(REROUTE)

    assert baseline["expected_delay_hours"] == 72
    assert baseline["on_time_pct"] == 1.4
    assert baseline["delay_risk_pct"] == 98.6
    assert baseline["connectivity_score"] == 68.75

    assert reroute["expected_delay_hours"] == 108
    assert reroute["on_time_pct"] == 0.29
    assert reroute["delay_risk_pct"] == 99.71
    assert reroute["connectivity_score"] == 47.27
    assert [leg["lane_key"] for leg in reroute["legs"]] == [
        "USNYC__USLAX",
        "USLAX__CNSHA",
    ]


def test_route_reliability_compounds_on_time_probability() -> None:
    baseline = route_reliability.route_reliability(BASELINE)
    reroute = route_reliability.route_reliability(REROUTE)

    assert reroute["on_time_pct"] <= baseline["on_time_pct"]
    assert reroute["expected_delay_hours"] > baseline["expected_delay_hours"]
