"""MMSI->IMO identity resolution with tie-break + first-class DQ counts.

ETL-01 / CONTEXT D-04/D-05/D-06. AIS position messages carry MMSI but usually a
null/0 ``imo``; only static (type-5) messages carry the IMO. This module builds
an MMSI->IMO lookup from the rows that DO carry a valid IMO (check-digit gated
via ``silver.imo.valid_imo``) and broadcasts it to the same MMSI's IMO-less
fixes (Pitfall 1: broadcast, do not per-row filter).

Identity policy:
  - D-04: IMO is the vessel natural key, never MMSI (MMSI is reassignable / a
    join key only). The mapping VALUE is always an IMO string.
  - D-05: a multi-IMO MMSI (reassignment / spoofing within the slice) tie-breaks
    by most-frequent IMO, then latest-seen ts among the tied. The ``collision``
    count is returned as a first-class DQ metric (the deck cites it).
  - D-06: a MMSI with NO valid IMO anywhere in the slice is excluded from the
    real conformed facts; the no-IMO drop count is reported (see
    ``dropped_mmsi_count``). "Valid IMO" = 7 digits passing the IMO check-digit.

The core ``resolve_mmsi_to_imo`` is pure and offline-unit-tested. An optional
column-projected Bronze reader (``rows_from_bronze``) mirrors the conditioning.py
classmethod-loader shape for the orchestrated land step; it is NOT exercised by
the unit tests (Pattern 1 pure/idempotent split).

Provenance: 04-RESEARCH.md § Code Examples "MMSI->IMO resolution with tie-break +
DQ counts" + Pitfall 1/Pitfall 3; 04-PATTERNS.md § silver/identity.py (analog
data_gen/conditioning.py first-class DQ + column-projected pq.read_table reuse).
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from silver.imo import valid_imo


def resolve_mmsi_to_imo(rows: Iterable[tuple]) -> tuple[dict, int]:
    """Resolve an MMSI->IMO mapping from ``(mmsi, imo_or_none, ts)`` rows.

    Only rows whose ``imo`` is non-None and passes ``valid_imo`` contribute to
    the mapping (Pitfall 3: filter to valid IMOs BEFORE counting distinct, so a
    null/0 IMO is never treated as a distinct collision value). For each MMSI:
      - a single distinct valid IMO maps directly;
      - >1 distinct valid IMO increments the collision count and tie-breaks by
        most-frequent IMO, then latest-seen ts among the tied (D-05).

    Returns ``(mapping, collision_count)`` where ``mapping`` is
    ``{mmsi: imo_str}`` (the value is an IMO string, never the MMSI — D-04). The
    no-IMO drop count is computed by ``dropped_mmsi_count`` against the caller's
    full set of MMSIs seen in the slice (D-06).
    """
    per_mmsi: dict = {}  # mmsi -> list[(imo_str, ts)] for valid IMOs only
    for mmsi, imo, ts in rows:
        if imo is not None and valid_imo(imo):
            per_mmsi.setdefault(mmsi, []).append((str(imo), ts))

    mapping: dict = {}
    collisions = 0
    for mmsi, pairs in per_mmsi.items():
        imos = [p[0] for p in pairs]
        distinct = set(imos)
        if len(distinct) > 1:
            collisions += 1
            counts = Counter(imos)
            top = max(counts.values())
            tied = [i for i, c in counts.items() if c == top]
            # most-frequent, then latest-seen ts among the tied (D-05).
            mapping[mmsi] = max(
                tied,
                key=lambda i: max(ts for im, ts in pairs if im == i),
            )
        else:
            mapping[mmsi] = next(iter(distinct))
    return mapping, collisions


def dropped_mmsi_count(all_mmsis: Iterable, mapping: dict) -> int:
    """No-IMO drop count (D-06): MMSIs seen in the slice but never resolved.

    ``all_mmsis`` is the full set of MMSIs that appeared in the slice (including
    IMO-less position rows); a MMSI not present as a mapping key never carried a
    valid IMO anywhere and is excluded from the real conformed facts.
    """
    return len(set(all_mmsis) - set(mapping.keys()))


def rows_from_bronze(table) -> list[tuple]:
    """Project a Bronze AIS pyarrow table to ``(mmsi, imo_or_none, ts)`` rows.

    Mirrors the conditioning.py classmethod-loader shape and the column-projected
    Bronze read convention (``ingest.pull_ais.READ_COLUMNS`` /
    ``pq.read_table(..., columns=[...])``): the land step reads
    ``mmsi``, ``imo``, ``base_date_time`` only and feeds these rows to
    ``resolve_mmsi_to_imo``. Kept thin so the core resolution stays pure and
    offline-testable. NOT touched by the unit tests.
    """
    mmsis = table.column("mmsi").to_pylist()
    imos = table.column("imo").to_pylist()
    ts = table.column("base_date_time").to_pylist()
    return list(zip(mmsis, imos, ts))
