"""data_gen/container_events.py — ~200k seeded container events (ING-03, D-11).

Analog: /Users/plosiewicz/Desktop/supply-chain/data_gen/movements.py — the
high-volume edge generator. Same determinism contract (per-instance seeded RNG,
ONE canonical row constructor, fixed iteration order, no wall-clock/uuid).

Each event references a real booking (its origin/dest lane), carries a
collision-safe deterministic ``_key`` (retry-then-counter, NEVER a uuid —
movements.py lines 257-326 pattern), and an LPI-conditioned ``delay_hours`` drawn
from ``conditioning.draw_delay_hours`` via ``numpy.default_rng`` (ING-04), rounded
to fixed decimals (Pitfall 7). An orphan-endpoint fail-loud guard (movements.py
lines 361-370) asserts every event's ``booking_id`` exists in the input set.
Every row carries ``provenance="synthetic"`` (D-14) + conformed keys.
"""

from __future__ import annotations

import datetime as dt
import random

from data_gen import network
from data_gen.conditioning import Conditioner
from lib.seeds import EVENTS_OFFSET, SEED

DEFAULT_COUNT = 200_000


def _event_row(
    _key: str,
    event_id: str,
    booking_id: str,
    container_id: str,
    origin_unlocode: str,
    dest_unlocode: str,
    vessel_imo: str,
    vessel_mmsi: str,
    event_stage: str,
    event_ts: str,
    delay_hours: float,
    provenance: str,
) -> dict:
    """Canonical key order — locks JSONL byte-determinism (P-4)."""
    return {
        "_key": _key,
        "event_id": event_id,
        "booking_id": booking_id,
        "container_id": container_id,
        "origin_unlocode": origin_unlocode,
        "dest_unlocode": dest_unlocode,
        "vessel_imo": vessel_imo,
        "vessel_mmsi": vessel_mmsi,
        "event_stage": event_stage,
        "event_ts": event_ts,
        "delay_hours": delay_hours,
        "provenance": provenance,
    }


def generate(
    *,
    seed: int = SEED + EVENTS_OFFSET,
    cond: Conditioner,
    bookings_rows: list[dict],
    count: int = DEFAULT_COUNT,
    _force_orphan: bool = False,
) -> list[dict]:
    """Return ``count`` container events, one per (booking, stage) draw.

    Delays are drawn from the destination country's LPI-conditioned distribution
    (ING-04). Deterministic in ``seed`` + ``cond`` + ``bookings_rows``.
    ``_force_orphan`` (test-only) emits a deliberately dangling booking ref to
    exercise the fail-loud orphan guard.
    """
    if not bookings_rows:
        raise RuntimeError("container_events.generate requires non-empty bookings_rows (run bookings first).")

    rng = random.Random(seed)
    valid_booking_ids = {b["booking_id"] for b in bookings_rows}
    days = network.quarter_days()
    n_days = len(days)
    n_stages = len(network.EVENT_STAGES)

    seen_keys: set[str] = set()
    rows: list[dict] = []
    for i in range(count):
        bk = rng.choice(bookings_rows)
        # test-only: emit an id guaranteed absent from the input set so the
        # fail-loud orphan guard is exercised.
        booking_id = "bkg_ORPHAN_TEST" if _force_orphan else bk["booking_id"]
        origin = bk["origin_unlocode"]
        dest = bk["dest_unlocode"]
        dest_country = network.PORT_COUNTRY[dest]
        stage = network.EVENT_STAGES[i % n_stages]

        # Deterministic per-event delay seed (seed + counter) so the numpy draw
        # is reproducible AND independent per event.
        delay = cond.draw_delay_hours(dest_country, seed=seed + i)

        # Event timestamp from the seeded quarter window (no wall-clock, D-12):
        # base day + a deterministic intra-day offset.
        base_day: dt.date = days[rng.randrange(n_days)]
        hour = rng.randrange(24)
        minute = rng.randrange(60)
        event_ts = dt.datetime(
            base_day.year, base_day.month, base_day.day, hour, minute
        ).isoformat()

        # Collision-safe deterministic _key (retry-then-counter; never uuid).
        candidate = f"evt_{booking_id}_{stage}"
        if candidate not in seen_keys:
            _key = candidate
        else:
            _key = f"evt_{booking_id}_{stage}_{i:06d}"
        seen_keys.add(_key)

        # Deterministic vessel identifiers (conformed keys: IMO + MMSI).
        vessel_seq = rng.randrange(1, 51)
        vessel_imo = f"IMO{9000000 + vessel_seq}"
        vessel_mmsi = str(366000000 + vessel_seq)

        rows.append(
            _event_row(
                _key=_key,
                event_id=f"evt_{i:06d}",
                booking_id=booking_id,
                container_id=f"CONT{i:07d}",
                origin_unlocode=origin,
                dest_unlocode=dest,
                vessel_imo=vessel_imo,
                vessel_mmsi=vessel_mmsi,
                event_stage=stage,
                event_ts=event_ts,
                delay_hours=delay,
                provenance="synthetic",
            )
        )

    # Orphan-endpoint fail-loud guard (movements.py lines 361-370): every event's
    # booking_id MUST reference a real booking — typos / off-by-one surface here,
    # not at Phase-4 conformance time.
    for e in rows:
        if e["booking_id"] not in valid_booking_ids:
            raise RuntimeError(f"orphan event endpoint: booking_id {e['booking_id']!r} not in bookings set")

    return rows
