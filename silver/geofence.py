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

from dataclasses import dataclass
from typing import Iterable

from ingest.pull_ais import wkb_point_lonlat
from silver.haversine import haversine_nm

# D-03 documented defaults (calibratable + documented downstream).
DEFAULT_RADIUS_NM = 5.0
DEFAULT_MIN_DWELL_HOURS = 1.0
# Debounce: require this many consecutive out-of-fence fixes before declaring
# exit, so a single boundary-jitter out-fix stays inside (Pitfall 7).
DEFAULT_DEBOUNCE = 2
# Same-fence re-entry coalesce window (hours). If a vessel exits a fence and
# re-enters the SAME fence within this window — i.e. it drifted out of the 5 nm
# circle, shifted berths, or the AIS track had a gap — the two stays are treated
# as ONE continuous port call rather than two separate calls. Without this, a
# debounced exit followed by re-entry into the same fence spawns a second call,
# and the consecutive same-port pair becomes a spurious zero-distance "voyage
# leg" (CR-01 root cause). Generous enough to absorb track gaps / berth shifts
# while still splitting a genuine round-trip departure-and-return (which always
# routes through a different fence in between).
DEFAULT_REENTRY_GAP_HOURS = 12.0

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


@dataclass
class _CallState:
    """Explicit per-vessel state for the port-call machine (CR-03).

    Replaces the prior read-only closure over loop-mutated locals — every
    transition assigns these fields unambiguously, so the state machine is
    provable and the reset paths after a debounced exit are auditable.

    ``current_fence``/``arrival_ts``/``last_in_ts`` describe an OPEN call (all
    None => no open call). ``out_run`` counts consecutive truly-out-of-fence
    (``fence is None``) fixes for the debounce. ``last_emitted_fence`` /
    ``last_emitted_departure_ts`` remember the most recently CLOSED call so a
    same-fence re-entry within the coalesce window can re-open that call instead
    of spawning a spurious second one (CR-01 root cause).
    """

    current_fence: str | None = None
    arrival_ts: object = None
    last_in_ts: object = None
    out_run: int = 0
    # True when the OPEN call resumed (coalesced into) a previously emitted call;
    # its emit overwrites that list entry in place rather than appending (CR-01).
    open_is_coalesced: bool = False
    last_emitted_fence: str | None = None
    last_emitted_arrival_ts: object = None
    last_emitted_departure_ts: object = None
    last_emitted_index: int | None = None


def derive_port_calls(
    fixes: Iterable[tuple],
    fences: dict,
    *,
    radius_nm: float = DEFAULT_RADIUS_NM,
    min_dwell_hours: float = DEFAULT_MIN_DWELL_HOURS,
    debounce: int = DEFAULT_DEBOUNCE,
    reentry_gap_hours: float = DEFAULT_REENTRY_GAP_HOURS,
) -> list[dict]:
    """Derive port-call candidates from ``(imo, wkb_or_none, ts)`` fixes.

    ``fences`` maps UN/LOCODE -> (port_lat, port_lon) centroids (D-01). Fixes are
    keyed by RESOLVED IMO (D-04) and processed per-vessel in time order. A call
    opens on entering a fence and closes after ``debounce`` consecutive
    truly-out-of-fence (``fence is None``) fixes; it is emitted only if
    ``departure_ts - arrival_ts >= min_dwell_hours`` (D-02). Null / short-WKB
    fixes are skipped, not fatal (CR-02 / Pitfall 5).

    State-machine transitions (CR-02 / CR-03):
      - OUTSIDE + enters fence F: open a call at F (or re-open the just-closed
        F call if the re-entry is within ``reentry_gap_hours`` — CR-01 coalesce).
      - INSIDE F + same fence F: extend dwell.
      - INSIDE F + a DIFFERENT fence G (``fence is not None``): a vessel cannot
        be in two 5 nm circles at once, so this is a FENCE SWITCH — close F and
        open G immediately, NOT a debounced exit (CR-02).
      - INSIDE F + out of all fences (``fence is None``): increment the debounce
        counter; close F only after ``debounce`` consecutive out fixes (Pitfall
        7 jitter tolerance).

    Returns a list of dicts ``{imo, unlocode, arrival_ts, departure_ts}`` in
    deterministic (vessel, arrival) order.
    """
    min_dwell_s = min_dwell_hours * 3600.0
    reentry_gap_s = reentry_gap_hours * 3600.0

    # Group fixes per vessel (resolved IMO), preserving input order within each.
    per_vessel: dict = {}
    for imo, wkb, ts in fixes:
        per_vessel.setdefault(imo, []).append((wkb, ts))

    calls: list[dict] = []

    def _emit(imo: str, st: _CallState) -> None:
        """Close the OPEN call in ``st`` (if any) and emit it if it dwelled.

        Records the emitted call's fence/timestamps + its index in ``calls`` so a
        subsequent same-fence re-entry within the coalesce window can re-open it
        (CR-01). Clears the open-call fields. Does NOT touch ``out_run`` — the
        caller owns the post-close reset so each transition is explicit (CR-03).
        """
        if st.current_fence is not None and st.arrival_ts is not None:
            row = {
                "imo": imo,
                "unlocode": st.current_fence,
                "arrival_ts": st.arrival_ts,
                "departure_ts": st.last_in_ts,
            }
            dwelled = (st.last_in_ts - st.arrival_ts).total_seconds() >= min_dwell_s
            if st.open_is_coalesced and st.last_emitted_index is not None:
                # This stay resumed a prior emitted call — overwrite it in place
                # (extends its departure) so the two stays are ONE row (CR-01),
                # never two consecutive same-port calls.
                calls[st.last_emitted_index] = row
            elif dwelled:
                calls.append(row)
                st.last_emitted_index = len(calls) - 1
            else:
                # Sub-dwell stay not emitted; it cannot be re-opened either.
                st.last_emitted_index = None
            st.last_emitted_fence = st.current_fence
            st.last_emitted_arrival_ts = st.arrival_ts
            st.last_emitted_departure_ts = st.last_in_ts
        st.current_fence = None
        st.arrival_ts = None
        st.last_in_ts = None
        st.open_is_coalesced = False

    def _open(st: _CallState, fence: str, ts) -> None:
        """Open a new call at ``fence`` — OR coalesce into the just-closed call.

        CR-01 root-cause fix: if ``fence`` is the same fence we most recently
        closed and the gap between that departure and ``ts`` is within
        ``reentry_gap_hours``, the vessel merely drifted out of the 5 nm circle /
        shifted berths / had a track gap — it is ONE continuous port call, not
        two. Re-open the emitted call in place (extend its departure as later
        fixes arrive) instead of starting a spurious second same-port call.
        """
        if (
            fence == st.last_emitted_fence
            and st.last_emitted_index is not None
            and st.last_emitted_departure_ts is not None
            and (ts - st.last_emitted_departure_ts).total_seconds() <= reentry_gap_s
        ):
            # Coalesce: resume the prior call (keep its original arrival). Its
            # emit will overwrite the existing list entry in place (CR-01).
            st.current_fence = fence
            st.arrival_ts = st.last_emitted_arrival_ts
            st.last_in_ts = ts
            st.out_run = 0
            st.open_is_coalesced = True
            return
        st.current_fence = fence
        st.arrival_ts = ts
        st.last_in_ts = ts
        st.out_run = 0
        st.open_is_coalesced = False

    for imo in sorted(per_vessel.keys()):
        # Sort each vessel's fixes by time (deterministic; mirrors thin_5min).
        rows = sorted(per_vessel[imo], key=lambda r: r[1])
        st = _CallState()

        for wkb, ts in rows:
            # CR-02 defensive drop: missing/short position fix -> skip, no crash.
            if wkb is None or len(wkb) < _MIN_WKB_LEN:
                continue
            lon, lat = wkb_point_lonlat(wkb)
            fence = _fence_for(lat, lon, fences, radius_nm)

            if st.current_fence is None:
                # OUTSIDE: open (or coalesce-resume) a call only on entering a fence.
                if fence is not None:
                    _open(st, fence, ts)
            elif fence == st.current_fence:
                # INSIDE the same fence: extend dwell, reset debounce.
                st.last_in_ts = ts
                st.out_run = 0
            elif fence is not None:
                # FENCE SWITCH (CR-02): a vessel cannot be in two 5 nm circles at
                # once, so a fix inside a DIFFERENT fence closes the current call
                # and opens the new one immediately — never a debounced "exit".
                # When coalescing applies _open re-opens the prior call instead;
                # but a switch to a different fence never coalesces (different
                # last_emitted_fence), so this always closes A and opens B.
                prev_arrival = st.arrival_ts
                prev_last_in = st.last_in_ts
                _emit(imo, st)
                # If the just-emitted call was sub-dwell it was not appended, but
                # the fence still switched — open B fresh from this fix.
                _open(st, fence, ts)
                del prev_arrival, prev_last_in
            else:
                # fence is None: truly out of all fences. Debounce the exit so a
                # single boundary-jitter out-fix does not split the call.
                st.out_run += 1
                if st.out_run >= debounce:
                    _emit(imo, st)
                    st.out_run = 0

        # End of track: close any still-open call (CR-03: explicit final close).
        _emit(imo, st)

    return calls
