"""Unit tests for the geofence port-call state machine — pure, no network/GCS.

Covers the four behaviors specified in 04-02-PLAN.md Task 2 (D-01/D-02/D-03):
  - enter -> dwell >= min-dwell -> exit emits exactly ONE call; arrival = first
    in-fence ts, departure = last in-fence ts
  - a sub-min-dwell clip emits ZERO calls (the min-dwell filter, D-02)
  - a single out-of-fence fix sandwiched by in-fence fixes (boundary jitter) is
    debounced into ONE continuous call, not split into two
  - a track entirely outside every fence emits zero calls (Pitfall 5 — expected)

The state machine keys vessels by RESOLVED IMO (not MMSI, D-04). Fixtures are
hand-built tiny tracks; nothing touches Bronze/GCS (Pattern 1 pure split). WKB
bytes are built with the same ``_wkb_point`` helper as test_pull_ais.py to prove
``wkb_point_lonlat`` reuse for geometry decode.
"""

from __future__ import annotations

import datetime as dt
import struct

from silver import geofence

# Houston/Galveston centroid (decimal degrees, US = negative longitude).
HOU_LAT, HOU_LON = 29.35, -94.7
# New York centroid — a SECOND fence hundreds of nm from Houston (fence-switch
# tests). It is also the "far" point relative to USHOU's 5 nm circle.
NYC_LAT, NYC_LON = 40.0, -73.0
# A point ~hundreds of nm away (well outside any 5 nm fence).
FAR_LAT, FAR_LON = 25.0, -80.0

FENCES = {"USHOU": (HOU_LAT, HOU_LON)}
# Two-fence map for fence-switch / different-fence transition tests.
FENCES_TWO = {"USHOU": (HOU_LAT, HOU_LON), "USNYC": (NYC_LAT, NYC_LON)}


def _wkb_point(lon: float, lat: float, little_endian: bool = True) -> bytes:
    """Build a WKB Point: byte-order flag + geom-type(1=Point) + lon + lat."""
    if little_endian:
        return struct.pack("<B", 1) + struct.pack("<I", 1) + struct.pack("<d", lon) + struct.pack("<d", lat)
    return struct.pack(">B", 0) + struct.pack(">I", 1) + struct.pack(">d", lon) + struct.pack(">d", lat)


def _ts(hour: float) -> dt.datetime:
    return dt.datetime(2024, 1, 1) + dt.timedelta(hours=hour)


def test_in_fence_true_inside_false_outside() -> None:
    """in_fence is True at the centroid and False hundreds of nm away."""
    assert geofence.in_fence(HOU_LAT, HOU_LON, HOU_LAT, HOU_LON, radius_nm=5.0)
    assert not geofence.in_fence(FAR_LAT, FAR_LON, HOU_LAT, HOU_LON, radius_nm=5.0)


def test_enter_dwell_exit_emits_one_call() -> None:
    """A track that enters, dwells >= min-dwell, then exits emits exactly one call."""
    # 5 in-fence fixes spanning hours 0..2 (>= 1 hr dwell), then an exit fix.
    fixes = [
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.5)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(1.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(2.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(3.0)),  # sustained exit
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(4.0)),
    ]
    calls = geofence.derive_port_calls(fixes, FENCES, radius_nm=5.0, min_dwell_hours=1.0)
    assert len(calls) == 1
    call = calls[0]
    assert call["imo"] == "9074729"
    assert call["unlocode"] == "USHOU"
    assert call["arrival_ts"] == _ts(0.0)
    assert call["departure_ts"] == _ts(2.0)


def test_sub_min_dwell_clip_emits_zero_calls() -> None:
    """A track that clips the fence for < min-dwell emits zero calls (D-02)."""
    fixes = [
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(0.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(1.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(1.25)),  # only 15 min in fence
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(2.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(3.0)),
    ]
    calls = geofence.derive_port_calls(fixes, FENCES, radius_nm=5.0, min_dwell_hours=1.0)
    assert calls == []


def test_boundary_jitter_debounced_into_one_call() -> None:
    """A single out-of-fence fix sandwiched by in-fence fixes does not split the call."""
    fixes = [
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.5)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(1.0)),  # single jitter out-fix
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(1.5)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(2.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(3.0)),  # sustained exit
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(4.0)),
    ]
    calls = geofence.derive_port_calls(fixes, FENCES, radius_nm=5.0, min_dwell_hours=1.0)
    assert len(calls) == 1
    # Debounced: one continuous call from first to last in-fence fix.
    assert calls[0]["arrival_ts"] == _ts(0.0)
    assert calls[0]["departure_ts"] == _ts(2.0)


def test_exit_and_reenter_same_fence_coalesces_into_one_call() -> None:
    """Exit a fence then re-enter the SAME fence within the gap window -> ONE call (CR-01).

    The vessel dwells, drifts fully out of the 5 nm circle for >= debounce fixes
    (a real exit is declared + the call closed), then re-enters the SAME fence a
    couple hours later (berth shift / drift / track gap). This is ONE continuous
    port call, not two — otherwise the consecutive same-port pair would become a
    spurious zero-distance "voyage leg" (the 92-leg pollution root cause).
    """
    fixes = [
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(1.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(2.0)),  # debounced exit (1)
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(3.0)),  # debounced exit (2) -> close
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(4.0)),  # re-enter SAME fence
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(5.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(8.0)),  # final sustained exit
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(9.0)),
    ]
    calls = geofence.derive_port_calls(
        fixes, FENCES, radius_nm=5.0, min_dwell_hours=1.0, reentry_gap_hours=12.0
    )
    assert len(calls) == 1
    assert calls[0]["unlocode"] == "USHOU"
    # Coalesced: arrival is the FIRST in-fence fix, departure the LAST.
    assert calls[0]["arrival_ts"] == _ts(0.0)
    assert calls[0]["departure_ts"] == _ts(5.0)


def test_direct_fence_switch_after_track_gap_emits_two_calls() -> None:
    """A direct A(inside) -> B(inside) transition is a FENCE SWITCH, not a debounced exit (CR-02).

    After a track gap the next fix is already inside a DIFFERENT fence with no
    out-of-fence fix between. The machine must close A and open B immediately —
    not absorb B as "jitter out of A" (which dropped the B call and overstated
    A's departure in the old code).
    """
    fixes = [
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(2.0)),  # A dwell >= 1 hr
        # --- track gap, next fix is directly inside fence B ---
        ("9074729", _wkb_point(NYC_LON, NYC_LAT), _ts(10.0)),
        ("9074729", _wkb_point(NYC_LON, NYC_LAT), _ts(12.0)),  # B dwell >= 1 hr
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(20.0)),  # sustained exit
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(21.0)),
    ]
    calls = geofence.derive_port_calls(fixes, FENCES_TWO, radius_nm=5.0, min_dwell_hours=1.0)
    assert len(calls) == 2
    assert calls[0]["unlocode"] == "USHOU"
    assert calls[0]["arrival_ts"] == _ts(0.0)
    assert calls[0]["departure_ts"] == _ts(2.0)  # NOT overstated to the gap
    assert calls[1]["unlocode"] == "USNYC"
    assert calls[1]["arrival_ts"] == _ts(10.0)
    assert calls[1]["departure_ts"] == _ts(12.0)


def test_track_gap_inside_one_fence_stays_one_call() -> None:
    """A long in-fence track gap (no out-of-fence fix) is still ONE continuous call (CR-03)."""
    fixes = [
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(1.0)),
        # --- large gap but the next fix is STILL inside the same fence ---
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(9.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(10.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(20.0)),  # sustained exit
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(21.0)),
    ]
    calls = geofence.derive_port_calls(fixes, FENCES, radius_nm=5.0, min_dwell_hours=1.0)
    assert len(calls) == 1
    assert calls[0]["arrival_ts"] == _ts(0.0)
    assert calls[0]["departure_ts"] == _ts(10.0)


def test_end_of_track_mid_debounce_emits_open_call_with_last_in_ts() -> None:
    """Track ends mid-debounce (1 out-fix, < debounce): the open call is still emitted (CR-03).

    departure_ts must be the last IN-fence ts, never the trailing out-fix ts.
    """
    fixes = [
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.0)),
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(2.0)),  # dwell >= 1 hr
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(3.0)),  # single out-fix, < debounce(2)
        # track ends here, mid-debounce
    ]
    calls = geofence.derive_port_calls(fixes, FENCES, radius_nm=5.0, min_dwell_hours=1.0)
    assert len(calls) == 1
    assert calls[0]["arrival_ts"] == _ts(0.0)
    assert calls[0]["departure_ts"] == _ts(2.0)  # last IN-fence ts, not the out-fix


def test_track_entirely_outside_emits_zero_calls() -> None:
    """A vessel whose whole track is outside all fences emits zero calls (Pitfall 5)."""
    fixes = [
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(0.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(1.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(2.0)),
    ]
    calls = geofence.derive_port_calls(fixes, FENCES, radius_nm=5.0, min_dwell_hours=1.0)
    assert calls == []


def test_null_and_short_wkb_fixes_dropped_not_fatal() -> None:
    """Null / short-WKB fixes are skipped (CR-02), valid in-fence fixes still call."""
    fixes = [
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(0.0)),
        ("9074729", None, _ts(0.5)),                 # null geometry -> skip
        ("9074729", b"\x01\x01\x00\x00\x00", _ts(1.0)),  # 5-byte truncated -> skip
        ("9074729", _wkb_point(HOU_LON, HOU_LAT), _ts(2.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(3.0)),
        ("9074729", _wkb_point(FAR_LON, FAR_LAT), _ts(4.0)),
    ]
    calls = geofence.derive_port_calls(fixes, FENCES, radius_nm=5.0, min_dwell_hours=1.0)
    assert len(calls) == 1
    assert calls[0]["arrival_ts"] == _ts(0.0)
    assert calls[0]["departure_ts"] == _ts(2.0)
