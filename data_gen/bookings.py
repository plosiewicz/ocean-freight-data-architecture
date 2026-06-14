"""data_gen/bookings.py — ~20k seeded freight bookings (ING-03, D-11).

Analog: /Users/plosiewicz/Desktop/supply-chain/data_gen/customers.py — a
Faker-identifier + weighted-categorical-draw vertex generator. Per-instance
``random.Random(seed)`` + ``Faker.seed_instance(seed)`` + ``numpy.default_rng``
are the byte-determinism defenses (D-12; never the global ``random.seed`` /
``Faker.seed`` class methods). ONE canonical row constructor (``_booking_row``)
locks JSONL key-insertion order (Pitfall P-4).

Lanes are drawn weighted by ``conditioning.lane_weight`` (ING-04) so the booking
distribution mirrors real LSCI connectivity x Comtrade trade demand — plausible,
not arbitrary. Every row carries ``provenance="synthetic"`` (D-14) and the
conformed keys (origin/dest UN/LOCODE, carrier SCAC) so Phase 4 conforms without
re-sourcing. ``booking_id`` is a deterministic counter (``bkg_000000``), never a
uuid; all dates derive from the seeded quarter window (no wall-clock).
"""

from __future__ import annotations

import datetime as dt
import random

from faker import Faker

from data_gen import network
from data_gen.conditioning import Conditioner
from lib.seeds import BOOKINGS_OFFSET, SEED

DEFAULT_COUNT = 20_000


def _booking_row(
    booking_id: str,
    shipper: str,
    consignee: str,
    origin_unlocode: str,
    dest_unlocode: str,
    carrier_scac: str,
    teu: int,
    commodity_hs2: str,
    booking_date: str,
    provenance: str,
) -> dict:
    """Canonical key order — locks JSONL byte-determinism (P-4)."""
    return {
        "booking_id": booking_id,
        "shipper": shipper,
        "consignee": consignee,
        "origin_unlocode": origin_unlocode,
        "dest_unlocode": dest_unlocode,
        "carrier_scac": carrier_scac,
        "teu": teu,
        "commodity_hs2": commodity_hs2,
        "booking_date": booking_date,
        "provenance": provenance,
    }


def generate(
    *,
    seed: int = SEED + BOOKINGS_OFFSET,
    cond: Conditioner,
    count: int = DEFAULT_COUNT,
) -> list[dict]:
    """Return ``count`` booking rows, lanes weighted by ``cond.lane_weight``.

    Deterministic in ``seed`` + ``cond``: same inputs -> byte-identical rows.
    ``count`` defaults to 20k (D-11); unit tests pass small counts for speed.
    """
    rng = random.Random(seed)
    faker = Faker()
    faker.seed_instance(seed)

    # Weighted lane pool (ING-04). Only lanes whose BOTH ports are known to the
    # conditioner are considered; lanes with zero weight (no trade/connectivity)
    # are dropped so they are never drawn; fail loud if NO lane is plausible.
    candidate_lanes = [
        lane
        for lane in network.LANES
        if lane[0] in cond.port_country and lane[1] in cond.port_country
    ]
    lanes = [lane for lane in candidate_lanes if cond.lane_weight(*lane) > 0.0]
    weights = [cond.lane_weight(*lane) for lane in lanes]
    if not lanes:
        raise RuntimeError(
            "no plausible lanes — every lane_weight is 0 (degenerate priors?). "
            "Refusing to fabricate an arbitrary network (ING-04 / D-13)."
        )

    days = network.quarter_days()
    n_days = len(days)
    hs2_pool = ("85", "84", "87", "27", "39", "62", "94", "73")  # common HS chapters

    rows: list[dict] = []
    for i in range(count):
        origin, dest = rng.choices(lanes, weights=weights, k=1)[0]
        # booking_date from the seeded quarter window (no wall-clock, D-12).
        day: dt.date = days[rng.randrange(n_days)]
        rows.append(
            _booking_row(
                booking_id=f"bkg_{i:06d}",
                shipper=faker.company(),
                consignee=faker.company(),
                origin_unlocode=origin,
                dest_unlocode=dest,
                carrier_scac=rng.choice(network.CARRIER_SCACS),
                teu=rng.randint(1, 400),
                commodity_hs2=rng.choice(hs2_pool),
                booking_date=day.isoformat(),
                provenance="synthetic",
            )
        )
    return rows
