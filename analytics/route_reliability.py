"""UC4 route reliability aggregation over the existing conditioning priors.

The Python mirror delegates per-country delay math to ``Conditioner`` and uses
the same route aggregation as the web serve seam: sum expected delays, multiply
per-leg on-time probabilities, and take weakest-link LSCI connectivity.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

from data_gen.conditioning import DELAY_LOGNORMAL_SIGMA, Conditioner
from data_gen.network import PORT_COUNTRY

ON_TIME_SLA_HOURS = 24.0

FALLBACK_LPI: dict[str, float] = {
    "USA": 3.9,
    "CHN": 3.7,
    "JPN": 3.95,
    "DEU": 4.1,
    "KOR": 3.8,
    "NLD": 4.0,
}
FALLBACK_LSCI: dict[str, float] = {
    "USA": 110.0,
    "CHN": 160.0,
    "JPN": 95.0,
    "DEU": 85.0,
    "KOR": 120.0,
    "NLD": 115.0,
}


def _norm_key(key: str) -> str:
    return key.removeprefix("ports/")


def _round2(value: float) -> float:
    return round(float(value), 2)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _lognormal_cdf(x: float, median_hours: float, sigma: float) -> float:
    if x <= 0.0:
        return 0.0
    if median_hours <= 0.0:
        return 1.0
    return _normal_cdf((math.log(x) - math.log(median_hours)) / sigma)


def _divide_by_max_norm(value: float, max_value: float) -> float:
    if not math.isfinite(max_value) or max_value <= 0.0:
        return 0.0
    return max(0.0, value) / max_value


def default_conditioner(cache_dir: Path = Path("data/priors")) -> Conditioner:
    """Load real local priors when present, else use the bounded UC4 fallback."""
    if (cache_dir / "lpi" / "lpi.json").exists() and (
        cache_dir / "lsci" / "lsci.json"
    ).exists():
        return Conditioner.from_local_cache(cache_dir=cache_dir, port_country=PORT_COUNTRY)
    return Conditioner(
        lsci_by_country=FALLBACK_LSCI,
        comtrade_od={},
        lpi_by_country=FALLBACK_LPI,
        port_country=PORT_COUNTRY,
    )


def leg_reliability(
    origin_port: str,
    dest_port: str,
    *,
    conditioner: Conditioner | None = None,
) -> dict[str, Any]:
    """Compute UC4 reliability for one directed leg."""
    cond = conditioner or default_conditioner()
    origin = _norm_key(origin_port)
    dest = _norm_key(dest_port)
    origin_country = cond.port_country[origin]
    dest_country = cond.port_country[dest]
    delay = cond.country_delay_params(dest_country)
    expected_delay = float(delay["mean_hours"])

    lsci_values = [float(v) for v in cond.lsci_by_country.values() if math.isfinite(v)]
    lsci_max = max(lsci_values, default=0.0)
    lsci_fallback = sum(lsci_values) / len(lsci_values) if lsci_values else 0.0
    origin_lsci = cond.lsci_by_country.get(origin_country, lsci_fallback)
    dest_lsci = cond.lsci_by_country.get(dest_country, lsci_fallback)
    connectivity = _divide_by_max_norm(origin_lsci, lsci_max) * _divide_by_max_norm(
        dest_lsci, lsci_max
    )

    on_time = _lognormal_cdf(ON_TIME_SLA_HOURS, expected_delay, DELAY_LOGNORMAL_SIGMA)
    return {
        "lane_key": f"{origin}__{dest}",
        "dest_country": dest_country,
        "expected_delay_hours": _round2(expected_delay),
        "on_time_pct": _round2(on_time * 100.0),
        "delay_risk_pct": _round2((1.0 - on_time) * 100.0),
        "connectivity_score": _round2(connectivity * 100.0),
        "lpi": _round2(float(delay["lpi"])),
    }


def route_reliability(
    hops: Sequence[dict[str, Any]],
    *,
    conditioner: Conditioner | None = None,
) -> dict[str, Any]:
    """Aggregate UC4 reliability over path hops."""
    cond = conditioner or default_conditioner()
    legs = [
        leg_reliability(str(hops[i - 1]["port"]), str(hops[i]["port"]), conditioner=cond)
        for i in range(1, len(hops))
    ]
    expected_delay = sum(float(leg["expected_delay_hours"]) for leg in legs)
    on_time_prob = math.prod(float(leg["on_time_pct"]) / 100.0 for leg in legs)
    connectivity = min((float(leg["connectivity_score"]) for leg in legs), default=0.0)
    return {
        "legs": legs,
        "expected_delay_hours": _round2(expected_delay),
        "on_time_pct": _round2(on_time_prob * 100.0),
        "delay_risk_pct": _round2((1.0 - on_time_prob) * 100.0),
        "connectivity_score": _round2(connectivity),
    }


__all__ = ["default_conditioner", "leg_reliability", "route_reliability"]
