"""Unit tests for the IMO 7-digit check-digit validator — offline only.

Covers the four behaviors specified in 04-01-PLAN.md Task 2 (ETL-01, CONTEXT
D-06 "valid IMO" = 7 digits passing the IMO check-digit):
  - golden case 9074729 is valid (check digit 9, verified across 3 sources)
  - string input "9074729" is accepted (str(imo).strip())
  - a 7-digit value with a wrong final digit is rejected
  - any non-7-digit / non-numeric / None value is rejected and NEVER raises

No network, GCS, or credentials are touched here — pure predicate math.
"""

from __future__ import annotations

from silver.imo import valid_imo


def test_golden_case_valid() -> None:
    """9074729 is the verified golden valid IMO (check digit 9)."""
    assert valid_imo(9074729) is True


def test_string_input_accepted() -> None:
    """A string IMO is coerced via str(imo).strip() and accepted."""
    assert valid_imo("9074729") is True
    assert valid_imo("  9074729  ") is True


def test_wrong_check_digit_rejected() -> None:
    """A 7-digit value whose final digit fails the check is rejected."""
    assert valid_imo(9074720) is False  # correct check digit is 9, not 0


def test_non_seven_digit_and_garbage_rejected_without_raising() -> None:
    """Length/digit guard: non-7-digit, non-numeric, and None all return False."""
    assert valid_imo(123456) is False      # 6 digits
    assert valid_imo(123456789) is False    # 9 digits
    assert valid_imo("0") is False          # too short
    assert valid_imo("ABCDEFG") is False    # non-numeric, 7 chars
    assert valid_imo(None) is False         # must not raise
    assert valid_imo("") is False           # empty


def test_all_zero_imo_rejected() -> None:
    """The all-zero sentinel 0000000 is rejected despite passing the check-digit (WR-06).

    0*7 + 0*6 + ... + 0*2 = 0, units digit 0 == digit[6] 0, so the raw arithmetic
    accepts it — but it is a zero-padding sentinel, not a real vessel IMO.
    """
    assert valid_imo("0000000") is False
    assert valid_imo(0) is False  # coerces to "0", too short anyway, but be explicit
