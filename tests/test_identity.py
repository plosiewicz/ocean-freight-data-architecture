"""Unit tests for MMSI->IMO resolution — pure, no network, no GCS.

Covers the four behaviors specified in 04-02-PLAN.md Task 1 (D-04/D-05/D-06):
  - a single MMSI carrying one repeated valid IMO maps to that IMO; 0 collisions
  - a multi-IMO MMSI tie-breaks to the most-frequent IMO; collision_count == 1
  - a multi-IMO MMSI at equal frequency tie-breaks to the latest-seen ts
  - a MMSI with no valid IMO anywhere is reported in the drop count and is NOT
    in the mapping; the mapping VALUE is always an IMO string, never the MMSI

All inputs are tiny hand-built (mmsi, imo_or_none, ts) tuples; nothing touches
Bronze/GCS (Pattern 1 pure-transform split).
"""

from __future__ import annotations

import datetime as dt

from silver import identity

# Two valid IMOs (pass the check digit): 9074729 (golden) and 9000015.
IMO_A = "9074729"
IMO_B = "9000015"


def _ts(minute: int) -> dt.datetime:
    return dt.datetime(2024, 1, 1, 0, minute, 0)


def test_single_valid_imo_maps_no_collision() -> None:
    """One MMSI, one repeated valid IMO -> maps to that IMO, 0 collisions."""
    rows = [
        (123456789, IMO_A, _ts(0)),
        (123456789, IMO_A, _ts(5)),
        (123456789, None, _ts(10)),  # IMO-less position row, ignored for mapping
    ]
    mapping, collisions = identity.resolve_mmsi_to_imo(rows)
    assert mapping == {123456789: IMO_A}
    assert collisions == 0
    # D-04: the mapping VALUE is the IMO, never the MMSI.
    assert mapping[123456789] == IMO_A
    assert mapping[123456789] != "123456789"


def test_multi_imo_tiebreak_most_frequent() -> None:
    """Two distinct valid IMOs, one more frequent -> most-frequent wins; 1 collision."""
    rows = [
        (123456789, IMO_A, _ts(0)),
        (123456789, IMO_A, _ts(5)),
        (123456789, IMO_A, _ts(10)),  # IMO_A x3
        (123456789, IMO_B, _ts(15)),  # IMO_B x1 (later but less frequent)
    ]
    mapping, collisions = identity.resolve_mmsi_to_imo(rows)
    assert mapping == {123456789: IMO_A}
    assert collisions == 1


def test_multi_imo_tiebreak_latest_on_frequency_tie() -> None:
    """Equal frequency -> tie-break to the latest-seen ts among the tied IMOs."""
    rows = [
        (123456789, IMO_A, _ts(0)),
        (123456789, IMO_A, _ts(5)),   # IMO_A x2, latest at minute 5
        (123456789, IMO_B, _ts(10)),
        (123456789, IMO_B, _ts(20)),  # IMO_B x2, latest at minute 20 -> wins
    ]
    mapping, collisions = identity.resolve_mmsi_to_imo(rows)
    assert mapping == {123456789: IMO_B}
    assert collisions == 1


def test_invalid_imo_rows_ignored_and_no_imo_mmsi_dropped() -> None:
    """Rows whose imo is None or fails valid_imo are ignored for mapping; a MMSI
    with NO valid IMO anywhere is counted in the drop count and absent (D-06)."""
    rows = [
        (111111111, IMO_A, _ts(0)),        # valid -> maps
        (111111111, None, _ts(5)),         # IMO-less -> ignored
        (222222222, "9000000", _ts(0)),    # 7 digits but BAD check digit -> ignored
        (222222222, None, _ts(5)),         # IMO-less -> ignored
        (333333333, "999", _ts(0)),        # not 7 digits -> ignored
    ]
    mmsis = {r[0] for r in rows}
    mapping, collisions = identity.resolve_mmsi_to_imo(rows)
    dropped = identity.dropped_mmsi_count(mmsis, mapping)

    assert mapping == {111111111: IMO_A}
    assert collisions == 0
    # 222222222 and 333333333 never had a valid IMO -> dropped, not in mapping.
    assert 222222222 not in mapping
    assert 333333333 not in mapping
    assert dropped == 2
