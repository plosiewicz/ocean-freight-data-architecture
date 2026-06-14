"""Unit tests for the priors fetch helpers — no network, no GCS, no remote API.

Covers the three behaviors specified in 03-04-PLAN.md Task 1:
  - LPI parser drops null-value aggregate rows, keeps country rows
    (countryiso3code + numeric value, T-03-11 input validation).
  - Comtrade request params are bounded (cmdCode=TOTAL, an explicit small
    reporter/partner/year set), never an unbounded all-partners/all-commodities
    call (Pitfall 6).
  - The optional COMTRADE_API_KEY is read from os.environ ONLY: keyless preview
    path when unset, env header when set; never hard-coded (T-03-10).

All inputs are tiny hand-built JSON fixtures; no remote endpoint is touched.
"""

from __future__ import annotations

from ingest import pull_priors


def test_lpi_filter_nulls() -> None:
    """LPI parser drops null-value aggregate rows; keeps numeric country rows."""
    # Shape mirrors the World Bank v2 indicator JSON: [metadata, [records...]].
    records = [
        # Aggregate row: null value, no iso3 -> dropped.
        {"countryiso3code": "", "country": {"value": "World"}, "value": None, "date": "2023"},
        # Aggregate region: null value -> dropped.
        {"countryiso3code": "EAS", "country": {"value": "East Asia & Pacific"}, "value": None, "date": "2023"},
        # Real country rows -> kept.
        {"countryiso3code": "USA", "country": {"value": "United States"}, "value": 3.84, "date": "2023"},
        {"countryiso3code": "SGP", "country": {"value": "Singapore"}, "value": 4.3, "date": "2023"},
    ]
    payload = [{"page": 1, "pages": 1, "per_page": 50, "total": 266}, records]

    kept = pull_priors.parse_lpi(payload)

    iso3s = [r["countryiso3code"] for r in kept]
    assert iso3s == ["USA", "SGP"]
    for r in kept:
        assert r["countryiso3code"]  # non-empty iso3
        assert isinstance(r["value"], (int, float))  # numeric value retained


def test_comtrade_params_bounded() -> None:
    """The Comtrade query is bounded: cmdCode=TOTAL + explicit small param set."""
    params = pull_priors.build_comtrade_params(
        reporter_code="842",
        partner_codes=["156", "392", "276"],
        period="2022",
    )

    # Bounded commodity: aggregate TOTAL, never an all-commodities sweep.
    assert params["cmdCode"] == "TOTAL"
    # Explicit, small partner set — not the "all partners" wildcard.
    assert params["partnerCode"] == "156,392,276"
    assert params["partnerCode"] != "all"
    # Explicit single reporter + period — not unbounded.
    assert params["reporterCode"] == "842"
    assert params["period"] == "2022"
    # Import flow only (M flow), keeps the result set small.
    assert params["flowCode"] == "M"


def test_api_key_from_env_only(monkeypatch) -> None:
    """COMTRADE_API_KEY is read from os.environ only; keyless preview by default."""
    # Case 1: unset -> keyless preview path, no auth header.
    monkeypatch.delenv("COMTRADE_API_KEY", raising=False)
    headers_unset = pull_priors.comtrade_headers()
    assert headers_unset == {} or "Ocp-Apim-Subscription-Key" not in headers_unset

    # Case 2: set -> the key is read from env and placed in the subscription header.
    monkeypatch.setenv("COMTRADE_API_KEY", "secret-key-value")
    headers_set = pull_priors.comtrade_headers()
    assert headers_set.get("Ocp-Apim-Subscription-Key") == "secret-key-value"
    # The key is never hard-coded in the module source.
    src = open(pull_priors.__file__).read()
    assert "secret-key-value" not in src
