"""Circular point-in-fence test + the canonical port-call state machine.

ETL-01 / CONTEXT D-01/D-02/D-03. Derives ``fact_port_call`` candidates from AIS
positions ONLY (never the AIS free-text destination, D-02):

  - D-01: port geofences are CIRCULAR — a radius around each port's WPI lat/lon
    centroid. ``in_fence`` tests ``haversine_nm(...) <= radius_nm``.
  - D-02: a port call = a vessel entering a fence and dwelling continuously for
    >= a minimum-dwell threshold; arrival = first in-fence fix, departure = last
    in-fence fix before a SUSTAINED exit.
  - D-03 (documented defaults, calibratable): radius ~5 nm, min-dwell ~1 hr.
    ``radius_nm`` / ``min_dwell_hours`` are parameters so derive.py / the land
    step can calibrate and document the final values + resulting call count.

The state machine keys vessels by RESOLVED IMO (not MMSI, D-04) and iterates
each vessel's time-ordered fixes (per-vessel groups, NOT row-wise ``.apply`` —
Anti-Patterns). It mirrors ``thin_5min``'s structural model (iterate indices in
time order, maintain a small Python state dict, emit deterministically) and
reuses ``ingest.pull_ais.wkb_point_lonlat`` for WKB decode (RESEARCH § Don't
Hand-Roll) with the CR-02 defensive null/short-WKB drop.

Debounce (Pitfall 7): a single out-of-fence fix sandwiched between in-fence
fixes is treated as still-inside; exit is declared only after ``debounce``
consecutive out-of-fence fixes, so a vessel jittering across the boundary is one
call, not several.

Provenance: 04-RESEARCH.md § Architecture Patterns Pattern 2 (point-in-fence) +
Pattern 3 (state machine) + Pitfall 5/Pitfall 7; ScienceDirect S0029801824001082
("Port call extraction from vessel location data"); reuses pull_ais helpers +
silver.haversine. 04-PATTERNS.md § silver/geofence.py.
"""

from __future__ import annotations

from typing import Iterable

from ingest.pull_ais import wkb_point_lonlat
from silver.haversine import haversine_nm

# D-03 documented defaults (calibratable + documented downstream).
DEFAULT_RADIUS_NM = 5.0
DEFAULT_MIN_DWELL_HOURS = 1.0
# Debounce: require this many consecutive out-of-fence fixes before declaring
# exit, so a single boundary-jitter out-fix stays inside (Pitfall 7).
DEFAULT_DEBOUNCE = 2

# Minimum WKB Point length: 1 byte-order flag + 4 type bytes + two 8-byte
# doubles = 21 bytes (matches ingest.pull_ais.filter_bbox CR-02 guard).
_MIN_WKB_LEN = 21


def in_fence(
    lat: float,
    lon: float,
    port_lat: float,
    port_lon: float,
    radius_nm: float = DEFAULT_RADIUS_NM,
) -> bool:
    """Return True iff (lat, lon) is within ``radius_nm`` of the port centroid (D-01)."""
    return haversine_nm(lat, lon, port_lat, port_lon) <= radius_nm


def _fence_for(
    lat: float,
    lon: float,
    fences: dict,
    radius_nm: float,
) -> str | None:
    """Return the UN/LOCODE of the first fence containing (lat, lon), else None."""
    for unlocode, (port_lat, port_lon) in fences.items():
        if in_fence(lat, lon, port_lat, port_lon, radius_nm):
            return unlocode
    return None


def derive_port_calls(
    fixes: Iterable[tuple],
    fences: dict,
    *,
    radius_nm: float = DEFAULT_RADIUS_NM,
    min_dwell_hours: float = DEFAULT_MIN_DWELL_HOURS,
    debounce: int = DEFAULT_DEBOUNCE,
) -> list[dict]:
    """Derive port-call candidates from ``(imo, wkb_or_none, ts)`` fixes.

    ``fences`` maps UN/LOCODE -> (port_lat, port_lon) centroids (D-01). Fixes are
    keyed by RESOLVED IMO (D-04) and processed per-vessel in time order. A call
    opens on entering a fence and closes after ``debounce`` consecutive
    out-of-fence (or different-fence) fixes; it is emitted only if
    ``departure_ts - arrival_ts >= min_dwell_hours`` (D-02). Null / short-WKB
    fixes are skipped, not fatal (CR-02 / Pitfall 5).

    Returns a list of dicts ``{imo, unlocode, arrival_ts, departure_ts}`` in
    deterministic (vessel, arrival) order.
    """
    min_dwell_s = min_dwell_hours * 3600.0

    # Group fixes per vessel (resolved IMO), preserving input order within each.
    per_vessel: dict = {}
    for imo, wkb, ts in fixes:
        per_vessel.setdefault(imo, []).append((wkb, ts))

    calls: list[dict] = []
    for imo in sorted(per_vessel.keys()):
        # Sort each vessel's fixes by time (deterministic; mirrors thin_5min).
        rows = sorted(per_vessel[imo], key=lambda r: r[1])

        current_fence: str | None = None
        arrival_ts = None
        last_in_ts = None
        out_run = 0  # consecutive out-of-current-fence fixes (debounce counter)

        def _close_and_emit() -> None:
            if current_fence is not None and arrival_ts is not None:
                if (last_in_ts - arrival_ts).total_seconds() >= min_dwell_s:
                    calls.append(
                        {
                            "imo": imo,
                            "unlocode": current_fence,
                            "arrival_ts": arrival_ts,
                            "departure_ts": last_in_ts,
                        }
                    )

        for wkb, ts in rows:
            # CR-02 defensive drop: missing/short position fix -> skip, no crash.
            if wkb is None or len(wkb) < _MIN_WKB_LEN:
                continue
            lon, lat = wkb_point_lonlat(wkb)
            fence = _fence_for(lat, lon, fences, radius_nm)

            if current_fence is None:
                # OUTSIDE: open a candidate only when we enter a fence.
                if fence is not None:
                    current_fence = fence
                    arrival_ts = ts
                    last_in_ts = ts
                    out_run = 0
            else:
                # INSIDE current_fence.
                if fence == current_fence:
                    last_in_ts = ts
                    out_run = 0
                else:
                    # Out of (or in a different) fence: count toward a sustained
                    # exit. A single sandwiched out-fix is debounced (Pitfall 7).
                    out_run += 1
                    if out_run >= debounce:
                        _close_and_emit()
                        # Reset; if this fix is itself inside a NEW fence, open it.
                        current_fence = fence
                        arrival_ts = ts if fence is not None else None
                        last_in_ts = ts if fence is not None else None
                        out_run = 0

        # End of track: close any still-open call.
        _close_and_emit()

    return calls
