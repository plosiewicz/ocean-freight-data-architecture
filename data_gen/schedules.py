"""data_gen/schedules.py — proforma liner schedules (ING-03).

Analogs: movements.py (priors-conditioned lane structure) + customers.py (Faker
carrier/service names). One proforma schedule per plausible lane (lane_weight >
0), with ``service_frequency`` (sailings/week) set from the normalized
``conditioning.lane_weight`` (RESEARCH recipe step 1) — busier lanes sail more
often. Same determinism contract: per-instance seeded RNG/Faker, ONE canonical
row constructor, no wall-clock/uuid. Every row carries ``provenance="synthetic"``
(D-14) + conformed keys (origin/dest UN/LOCODE, carrier SCAC).
"""

from __future__ import annotations

import random

from faker import Faker

from data_gen import network
from data_gen.conditioning import Conditioner
from lib.seeds import SCHEDULES_OFFSET, SEED

# Max sailings/week for the busiest lane; scaled down by normalized lane_weight.
MAX_SERVICE_FREQUENCY = 7
MIN_SERVICE_FREQUENCY = 1


def _schedule_row(
    service_id: str,
    service_name: str,
    origin_unlocode: str,
    dest_unlocode: str,
    carrier_scac: str,
    service_frequency: int,
    transit_days: int,
    provenance: str,
) -> dict:
    """Canonical key order — locks JSONL byte-determinism (P-4)."""
    return {
        "service_id": service_id,
        "service_name": service_name,
        "origin_unlocode": origin_unlocode,
        "dest_unlocode": dest_unlocode,
        "carrier_scac": carrier_scac,
        "service_frequency": service_frequency,
        "transit_days": transit_days,
        "provenance": provenance,
    }


def generate(*, seed: int = SEED + SCHEDULES_OFFSET, cond: Conditioner) -> list[dict]:
    """Return one proforma schedule per plausible lane (lane_weight > 0).

    Deterministic in ``seed`` + ``cond``: lanes are iterated in fixed
    ``network.LANES`` order so output is byte-stable. ``service_frequency`` is
    set from the normalized lane_weight (busier lane -> more sailings/week).
    """
    rng = random.Random(seed)
    faker = Faker()
    faker.seed_instance(seed)

    candidate_lanes = [
        lane
        for lane in network.LANES
        if lane[0] in cond.port_country and lane[1] in cond.port_country
    ]
    plausible = [(lane, cond.lane_weight(*lane)) for lane in candidate_lanes]
    plausible = [(lane, w) for lane, w in plausible if w > 0.0]
    if not plausible:
        raise RuntimeError(
            "no plausible lanes for schedules — every lane_weight is 0 (ING-04 / D-13)."
        )

    max_w = max(w for _, w in plausible)

    rows: list[dict] = []
    for idx, (lane, weight) in enumerate(plausible):
        origin, dest = lane
        # service_frequency scaled from normalized lane_weight into [MIN, MAX].
        norm = weight / max_w if max_w > 0 else 0.0
        freq = MIN_SERVICE_FREQUENCY + round(norm * (MAX_SERVICE_FREQUENCY - MIN_SERVICE_FREQUENCY))
        rows.append(
            _schedule_row(
                service_id=f"svc_{idx:04d}",
                service_name=f"{faker.word().title()} Express",
                origin_unlocode=origin,
                dest_unlocode=dest,
                carrier_scac=rng.choice(network.CARRIER_SCACS),
                service_frequency=int(freq),
                transit_days=rng.randint(10, 45),
                provenance="synthetic",
            )
        )
    return rows
