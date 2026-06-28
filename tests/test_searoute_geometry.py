"""Wave-0 determinism contract for the offline sea-route precompute (REQ-14-4).

Offline, credential-free unit test. Pins the behavior contract that
``lib/searoute_geometry.py`` must satisfy for every downstream geometry task
(Plan 04 freeze, Plan 05 render) to bake/draw real polylines:

  1. determinism      — same (origin, dest, restrict) twice => byte-identical lists;
  2. distinctness     — Suez-forced (restrict ``panama``) differs from Panama-forced
                        (restrict ``suez``) for an Asia<->USEC O-D (the XOR split lever);
  3. endpoint match   — first/last point ~= the passed origin/dest after normalization
                        (RESEARCH Pitfall 2 tolerance);
  4. lon normalization — every emitted lon obeys the documented convention range
                        ([-180, 180], Option B — RESEARCH Pitfall 1);
  5. rounding         — every coord equals its own 12-place round (so
                        ``freeze_uc._round_floats`` is a no-op; byte-stable golden).

Asserts DIRECTION / SHAPE only — never pins specific coordinate magnitudes
(RESEARCH Anti-Pattern: do not hard-code the frozen numbers).

Mirrors the offline import-or-skip-RED idiom from ``tests/test_arango_load.py``;
``pytest.skip``s (reports RED) until ``lib/searoute_geometry.py`` exists.
"""

from __future__ import annotations

import pytest

# Asia<->USEC O-D used for the distinctness/endpoint checks. Coords are
# [lon, lat] (searoute's lon-first order), sourced from
# graph_loader._PORT_CENTROID_FALLBACK (USNYC, CNSHA) — the offline coord source
# of truth (no second coord table). The exact magnitudes are NOT asserted.
USNYC = [-74.02, 40.70]
CNSHA = [121.47, 31.23]


def _import():
    """Import the module under test; skip-as-RED until Task 2 lands it."""
    try:
        from lib import searoute_geometry  # noqa: F401
    except ImportError as exc:  # pragma: no cover - RED until Task 2
        pytest.skip(f"lib.searoute_geometry not built yet: {exc}")
    return searoute_geometry


def test_polyline_is_nonempty_lonlat_pairs():
    """polyline_for returns a non-empty list of [lon, lat] pairs."""
    sg = _import()
    line = sg.polyline_for(USNYC, CNSHA)
    assert isinstance(line, list) and len(line) > 0
    for pt in line:
        assert isinstance(pt, list) and len(pt) == 2


def test_determinism_byte_identical():
    """Same (origin, dest, restrict) twice => byte-identical lists (no RNG)."""
    sg = _import()
    first = sg.polyline_for(USNYC, CNSHA, restrict=("panama",))
    second = sg.polyline_for(USNYC, CNSHA, restrict=("panama",))
    assert first == second


def test_suez_forced_differs_from_panama_forced():
    """Suez-forced (restrict panama) != Panama-forced (restrict suez) for Asia<->USEC."""
    sg = _import()
    suez_forced = sg.polyline_for(USNYC, CNSHA, restrict=("panama",))
    panama_forced = sg.polyline_for(USNYC, CNSHA, restrict=("suez",))
    # Distinct length and/or coordinates — direction/shape only, no magnitudes.
    assert suez_forced != panama_forced


def test_endpoint_coincidence_after_normalization():
    """First/last point ~= the passed origin/dest after normalization (Pitfall 2)."""
    sg = _import()
    line = sg.polyline_for(USNYC, CNSHA, restrict=("suez",))  # crosses antimeridian
    first, last = line[0], line[-1]
    norm_dest_lon = sg._normalize_lon([CNSHA[0], CNSHA[1]])[0]
    assert first[0] == pytest.approx(USNYC[0], abs=1e-3)
    assert first[1] == pytest.approx(USNYC[1], abs=1e-3)
    assert last[0] == pytest.approx(norm_dest_lon, abs=1e-3)
    assert last[1] == pytest.approx(CNSHA[1], abs=1e-3)


def test_every_lon_in_documented_range():
    """Every emitted lon obeys the documented Option-B range [-180, 180]."""
    sg = _import()
    for restrict in [(), ("panama",), ("suez",)]:
        for lon, _lat in sg.polyline_for(USNYC, CNSHA, restrict=restrict):
            assert -180.0 <= lon <= 180.0


def test_every_coord_is_12_place_rounded():
    """Every coord equals its own 12-place round (freeze_uc._round_floats no-op)."""
    sg = _import()
    for lon, lat in sg.polyline_for(USNYC, CNSHA, restrict=("panama",)):
        assert lon == round(lon, 12)
        assert lat == round(lat, 12)
