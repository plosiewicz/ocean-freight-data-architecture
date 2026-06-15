"""Central determinism seed + per-entity stream offsets (D-12, ING-03).

Every data_gen/* generator derives its RNG from ``SEED + <ENTITY>_OFFSET`` so the
per-entity streams are independent yet fully reproducible. The offsets MUST stay
distinct (verified in tests/test_lib.py::test_seeds_offsets_distinct). These are
the byte-identical synthetic-data anchors recorded alongside synthetic.sha256.

Usage:
    rng = random.Random(SEED + BOOKINGS_OFFSET)
    nprng = numpy.random.default_rng(SEED + EVENTS_OFFSET)
    faker = Faker(); faker.seed_instance(SEED + SCHEDULES_OFFSET)
"""

from __future__ import annotations

SEED: int = 20240614

# Per-entity stream offsets — MUST be distinct.
BOOKINGS_OFFSET: int = 1000
EVENTS_OFFSET: int = 2000
SCHEDULES_OFFSET: int = 3000
# Phase-4 Silver: synthetic vessel->carrier operated_by / carrier assignment
# (D-09 — AIS has no operator field; reference-assigned carrier is synthetic).
OPERATED_BY_OFFSET: int = 4000
