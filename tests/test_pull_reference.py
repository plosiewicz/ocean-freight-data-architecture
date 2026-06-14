"""Unit tests for the reference fetch/land helpers — no network, no GCS.

Covers the two behaviors specified in 03-03-PLAN.md Task 1:
  - test_chokepoints_complete: reference/chokepoints.csv contains EXACTLY the 7
    Phase-2 D-09 nodes with numeric (float-parseable) lat/lon. This is the
    zero-rework graph-projection contract for Phase 6.
  - test_wpi_source_selection: when a scripted WPI fetch returns 403 (mocked /
    WAF rejected), the loader falls back to the M1 sample path rather than
    crashing; when 200 with non-WAF bytes, it uses the fetched bytes. A WAF page
    served as 200 is treated as a rejection (T-03-07).

Inputs are the committed chokepoints.csv and tiny hand-built fixtures; no remote
endpoint is touched.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ingest import pull_reference

CHOKEPOINTS_CSV = Path(__file__).resolve().parent.parent / "reference" / "chokepoints.csv"


def test_chokepoints_complete() -> None:
    """chokepoints.csv has exactly the 7 D-09 nodes with float lat/lon."""
    with open(CHOKEPOINTS_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    keys = {r["key"] for r in rows}
    assert keys == {
        "CHK_SUEZ",
        "CHK_PANAMA",
        "CHK_MALACCA",
        "CHK_GIBRALTAR",
        "CHK_BABMANDEB",
        "CHK_HORMUZ",
        "CHK_GOODHOPE",
    }
    assert len(rows) == 7  # exactly 7 — no extras, no duplicates

    for r in rows:
        # Every coordinate parses as a float (usable for GEO_DISTANCE placement).
        lat = float(r["lat"])
        lon = float(r["lon"])
        assert -90.0 <= lat <= 90.0
        assert -180.0 <= lon <= 180.0
        assert r["name"]  # human-readable label present

    # The module's own validator agrees (drift guard before landing).
    pull_reference.validate_chokepoints(rows)


def test_wpi_source_selection_200_uses_fetched_bytes() -> None:
    """A genuine HTTP 200 with non-WAF bytes uses the fetched payload."""
    body = b"World Port Number,Region Name,Main Port Name,UN/LOCODE\n60710,...,USHOU\n"
    source, payload = pull_reference.select_wpi_source(
        status_code=200, body=body, sample_exists=True
    )
    assert source == "fetched"
    assert payload == body


def test_wpi_source_selection_403_falls_back_to_m1_sample() -> None:
    """A 403/WAF rejection falls back to the M1 sample (never crashes)."""
    source, payload = pull_reference.select_wpi_source(
        status_code=403, body=b"<html>Request Rejected ... support ID</html>",
        sample_exists=True,
    )
    assert source == "m1_sample"
    assert payload is None


def test_wpi_source_selection_200_waf_body_is_rejected() -> None:
    """A WAF 'Request Rejected' page served as 200 is NOT landed as the reference."""
    waf_page = b"<html><body>Request Rejected ... support ID 12345</body></html>"
    source, _ = pull_reference.select_wpi_source(
        status_code=200, body=waf_page, sample_exists=True
    )
    assert source == "m1_sample"  # treated as rejection, falls back


def test_wpi_source_selection_no_fallback_raises_for_human_verify() -> None:
    """With no usable fetch and no M1 sample, raise so the CLI routes to human-verify."""
    with pytest.raises(pull_reference.WpiUnavailable):
        pull_reference.select_wpi_source(
            status_code=403, body=b"Request Rejected", sample_exists=False
        )
