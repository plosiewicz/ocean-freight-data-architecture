"""Shared synthetic network constants: ports, countries, carriers, quarter window.

The synthetic ocean-freight network spans the four real US AIS ports (conformed
to ``dim_port`` by UN/LOCODE — same keys as ingest/pull_ais.py PORT_BBOXES) plus
the five foreign partner ports the bounded Comtrade O-D pull names (reporter
842=USA imports from CN/JP/DE/KR/NL). Lanes are international US<->partner pairs
so the LSCI x LSCI x Comtrade conditioning is meaningful.

All values are CONSTANTS — no wall-clock, no randomness here. The quarter window
matches the AIS slice anchor (Q1 2024) so synthetic events conform temporally to
the real positions (D-05 dt= partitioning).

Provenance: ingest/pull_ais.py PORT_BBOXES (the four US UN/LOCODEs); 03-RESEARCH.md
§ Priors conditioning (bounded partner set); 03-CONTEXT.md D-04/D-05.
"""

from __future__ import annotations

import datetime as dt

# Port -> ISO3 country. US ports keyed exactly as ingest/pull_ais.py PORT_BBOXES.
PORT_COUNTRY: dict[str, str] = {
    # US ports (the four real AIS ports — conform to dim_port via UN/LOCODE)
    "USHOU": "USA",  # Houston / Galveston
    "USLAX": "USA",  # Los Angeles / Long Beach
    "USNYC": "USA",  # New York / New Jersey
    "USSAV": "USA",  # Savannah
    # Foreign partner ports (the bounded Comtrade partner set)
    "CNSHA": "CHN",  # Shanghai
    "JPTYO": "JPN",  # Tokyo
    "DEHAM": "DEU",  # Hamburg
    "KRPUS": "KOR",  # Busan
    "NLRTM": "NLD",  # Rotterdam
}

US_PORTS: tuple[str, ...] = ("USHOU", "USLAX", "USNYC", "USSAV")
FOREIGN_PORTS: tuple[str, ...] = ("CNSHA", "JPTYO", "DEHAM", "KRPUS", "NLRTM")

# All directed international lanes (US<->foreign, both directions). Lanes never
# connect two US ports or two foreign ports — this is an ocean trade network.
LANES: tuple[tuple[str, str], ...] = tuple(
    [(us, fp) for us in US_PORTS for fp in FOREIGN_PORTS]
    + [(fp, us) for us in US_PORTS for fp in FOREIGN_PORTS]
)

# All directed US->US lanes (origin != dest). These are a SEPARATE proforma path
# (D-02): the international LSCI x LSCI x Comtrade conditioner zero-weights US->US
# pairs (comtrade_od[(USA, USA)] = 0.0 -> lane_weight 0.0 -> filtered out of the
# conditioned LANES, RESEARCH A4 / Pitfall 1). The real AIS slice is US-only, so
# every real voyage leg is US->US; a US->US proforma row is what lets
# schedule_delta = actual - scheduled populate. Emitted in fixed (US_PORTS x
# US_PORTS) order for byte-determinism; never folded into the conditioned LANES.
US_US_LANES: tuple[tuple[str, str], ...] = tuple(
    (o, d) for o in US_PORTS for d in US_PORTS if o != d
)

# Carrier SCAC codes (4-letter, deterministic set — real liner carriers).
CARRIER_SCACS: tuple[str, ...] = ("MAEU", "MSCU", "CMDU", "HLCU", "COSU", "ONEY", "EGLV", "HMMU")

# Seeded quarter window — matches the AIS Q1 2024 anchor (no wall-clock, D-12).
QUARTER_START: dt.date = dt.date(2024, 1, 1)
QUARTER_END: dt.date = dt.date(2024, 3, 31)
# Quarter-start anchor (D-05). NOTE (CR-03): dated synthetic streams (events,
# bookings) are partitioned by EACH RECORD's OWN natural date at landing — they
# do NOT all sit under this anchor. This constant is now only the landing anchor
# for the TIMELESS schedules stream (proforma, one-per-lane, no per-record date),
# so a non-date value never masquerades under a dt= key for dated records.
EVENT_PARTITION_DT: str = QUARTER_START.isoformat()

# Container event lifecycle stages (fixed order -> byte-stable iteration).
EVENT_STAGES: tuple[str, ...] = (
    "booking_confirmed",
    "gate_in_origin",
    "vessel_loaded",
    "vessel_departed",
    "vessel_arrived",
    "gate_out_dest",
)


def quarter_days() -> list[dt.date]:
    """Inclusive list of the quarter's days, in fixed order (no wall-clock)."""
    days: list[dt.date] = []
    d = QUARTER_START
    while d <= QUARTER_END:
        days.append(d)
        d += dt.timedelta(days=1)
    return days
