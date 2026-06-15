"""silver/conform.py — conform the four real dims to canonical keys + SCD + provenance.

ETL-01 / criteria 1 (conformed entities born here with standardized codes +
deterministic INT64 surrogate keys) + 4 (row-level provenance flag, D-11).
CONTEXT D-09 (dim_carrier + vessel->carrier operated_by use synthetic/reference
assignment) / D-11 (every Silver row carries provenance in {real, synthetic}).

Pure, deterministic, offline-testable transforms (Pattern 1 split — no I/O here;
landing is the separate land_silver step). The four conformed dims:
  - dim_port   (SCD1) — current snapshot, UN/LOCODE natural key, WPI centroid.
  - dim_lane   (SCD1) — current snapshot, lane_key natural key.
  - dim_vessel (SCD2) — IMO natural key (gated by valid_imo), effective_from/
    effective_to/is_current/row_hash, run_date-anchored versioning.
  - dim_carrier(SCD2) — SCAC natural key from data_gen.network.CARRIER_SCACS,
    provenance="synthetic" (reference-assigned).

SCD in a batch Parquet world (RESEARCH Pattern 5): surrogate keys + content-hash
change detection. ``effective_from`` is anchored to a passed-in ``run_date`` (the
slice's max event date), NEVER ``datetime.now()`` (Anti-Pattern — breaks the
idempotent full-partition reload, threat T-04-07).

HONESTY NOTE (A6): the bounded 7-day AIS slice is expected to produce ZERO real
SCD2 change events (vessel/carrier attributes are static within a week). The SCD2
capability is built and unit-tested (the two-snapshot test proves versioning
fires), but the slice itself will show all is_current=True — carried to the deck.

The WPI centroid sanity assertion (Pitfall 6 / threat T-04-06) fails loud if a
target port's centroid falls outside its Phase-3 PORT_BBOXES box — catching DMS /
wrong-sign coordinate-format errors BEFORE any derivation consumes the dim.

Provenance: 04-RESEARCH.md § Architecture Patterns Pattern 5 (SCD in batch
Parquet) + § Code Examples "Surrogate key assignment"; Pitfall 6 (WPI coordinate
format); 04-PATTERNS.md § silver/conform.py (surrogate / SCD / provenance /
centroid assert / seeded operated_by); 02-CONTEXT.md (SCD2 vessel/carrier, SCD1
port/lane, surrogate-key convention).
"""

from __future__ import annotations

import datetime as dt
import hashlib

import numpy as np
import pandas as pd

from data_gen.network import CARRIER_SCACS
from ingest.pull_ais import PORT_BBOXES
from lib.seeds import OPERATED_BY_OFFSET, SEED
from silver.imo import valid_imo

# SCD2 tracked attributes per dim — the content-hash change-detection inputs.
_VESSEL_TRACKED = ("vessel_name",)
_CARRIER_TRACKED = ("carrier_name",)

# Far-future sentinel for an open (current) SCD2 row's effective_to. Using a
# sentinel date (not NULL) keeps the column a single dtype across Parquet round
# trips; current rows are identified by is_current, not by a NULL effective_to.
EFFECTIVE_TO_OPEN = dt.date(9999, 12, 31)


# --------------------------------------------------------------------------- #
# Surrogate keys
# --------------------------------------------------------------------------- #
def assign_surrogate(df: pd.DataFrame, natural_key_col: str) -> pd.DataFrame:
    """Deterministic 1-based INT64 surrogate by sorting on the natural key.

    Sorting on the natural key (stable) makes the surrogate->natural mapping
    identical across re-runs on the same input (Phase-2 surrogate-key
    convention; RESEARCH § Code Examples). Returns a NEW frame (no mutation).
    """
    out = df.sort_values(natural_key_col, kind="stable").reset_index(drop=True)
    out["surrogate_key"] = (out.index.astype("int64") + 1)  # 1-based
    return out


def _row_hash(values: tuple) -> str:
    """Content hash of the SCD2-tracked attributes (non-security use — hashlib).

    Used only for SCD2 change detection (V6: no cryptographic claim). A '|'
    joiner with str() coercion keeps the hash stable and order-sensitive.
    """
    payload = "|".join(str(v) for v in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# SCD1 dims (current snapshot — dim_port, dim_lane)
# --------------------------------------------------------------------------- #
def conform_dim_port(wpi: pd.DataFrame) -> pd.DataFrame:
    """Conform dim_port (SCD1): UN/LOCODE natural key + WPI centroid + surrogate.

    Fails loud (Pitfall 6) if any of the four target ports present in ``wpi`` has
    a centroid outside its PORT_BBOXES box. Real reference dim -> provenance="real".
    """
    assert_centroids_in_bbox(wpi)
    cols = ["unlocode", "lat", "lon"]
    missing = [c for c in cols if c not in wpi.columns]
    if missing:
        raise ValueError(f"dim_port WPI input missing columns {missing} (D-01).")
    dim = wpi[cols].copy()
    dim = assign_surrogate(dim, "unlocode")
    dim["provenance"] = "real"
    return dim[["surrogate_key", "unlocode", "lat", "lon", "provenance"]]


def conform_dim_lane(lanes: pd.DataFrame) -> pd.DataFrame:
    """Conform dim_lane (SCD1): lane_key natural key + surrogate; provenance='real'."""
    if "lane_key" not in lanes.columns:
        raise ValueError("dim_lane input missing 'lane_key' column.")
    dim = lanes.copy()
    dim = assign_surrogate(dim, "lane_key")
    dim["provenance"] = "real"
    front = ["surrogate_key", "lane_key"]
    rest = [c for c in dim.columns if c not in front]
    return dim[front + rest]


# --------------------------------------------------------------------------- #
# SCD2 dims (versioned — dim_vessel, dim_carrier)
# --------------------------------------------------------------------------- #
def _build_scd2_snapshot(
    snapshot: pd.DataFrame,
    natural_key_col: str,
    tracked: tuple[str, ...],
    run_date: dt.date,
    provenance: str,
) -> pd.DataFrame:
    """Build a fresh all-current SCD2 frame from a computed snapshot.

    Each row: surrogate_key, natural key, tracked attrs, effective_from=run_date,
    effective_to=open sentinel, is_current=True, row_hash(content of tracked).
    """
    dim = assign_surrogate(snapshot.copy(), natural_key_col)
    dim["effective_from"] = run_date
    dim["effective_to"] = EFFECTIVE_TO_OPEN
    dim["is_current"] = True
    dim["row_hash"] = [
        _row_hash(tuple(row[c] for c in tracked)) for _, row in dim.iterrows()
    ]
    dim["provenance"] = provenance
    front = ["surrogate_key", natural_key_col, *tracked]
    rest = [c for c in dim.columns if c not in front]
    return dim[front + rest]


def _apply_scd2_reload(
    existing: pd.DataFrame,
    new_snapshot: pd.DataFrame,
    natural_key_col: str,
    run_date: dt.date,
) -> pd.DataFrame:
    """Content-hash SCD2 reload: close changed current rows, append new versions.

    For each natural key in ``new_snapshot``, compare its row_hash to the existing
    CURRENT row's row_hash. If different (a tracked attr changed), close the old
    row (effective_to=run_date, is_current=False) and append the new current row.
    Unchanged keys keep their existing current row (idempotent reload).
    """
    out = existing.copy()
    current_by_key = {
        row[natural_key_col]: idx
        for idx, row in out[out["is_current"]].iterrows()
    }
    appended: list[dict] = []
    for _, new_row in new_snapshot.iterrows():
        key = new_row[natural_key_col]
        if key in current_by_key:
            idx = current_by_key[key]
            if out.at[idx, "row_hash"] != new_row["row_hash"]:
                # Change detected: close the old current row, open a new one.
                out.at[idx, "effective_to"] = run_date
                out.at[idx, "is_current"] = False
                appended.append(new_row.to_dict())
        else:
            # Brand-new natural key not seen before -> its own current row.
            appended.append(new_row.to_dict())
    if appended:
        out = pd.concat([out, pd.DataFrame(appended)], ignore_index=True)
    return out.reset_index(drop=True)


def conform_dim_vessel(
    snapshot: pd.DataFrame,
    *,
    run_date: dt.date,
    existing: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Conform dim_vessel (SCD2): IMO natural key gated by valid_imo.

    ``snapshot`` carries the current computed vessel identities (imo + tracked
    attrs). Invalid IMOs are rejected (D-04/D-06, threat T-04-08) — the caller
    (identity.py) has already resolved/validated, but conform re-asserts the gate.
    With ``existing`` provided, performs the content-hash SCD2 reload.
    """
    if "imo" not in snapshot.columns:
        raise ValueError("dim_vessel snapshot missing 'imo' natural key column.")
    bad = [imo for imo in snapshot["imo"] if not valid_imo(imo)]
    if bad:
        raise ValueError(
            f"dim_vessel admits only valid-IMO natural keys; rejected {bad} "
            "(D-04/D-06, threat T-04-08)."
        )
    fresh = _build_scd2_snapshot(
        snapshot, "imo", _VESSEL_TRACKED, run_date, provenance="real"
    )
    if existing is None:
        return fresh
    return _apply_scd2_reload(existing, fresh, "imo", run_date)


def conform_dim_carrier(
    *,
    run_date: dt.date,
    existing: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Conform dim_carrier (SCD2): SCAC natural key from CARRIER_SCACS.

    Carriers are reference-assigned, so provenance="synthetic" (D-09/D-11,
    threat T-04-09). The carrier_name tracked attribute is a stable label derived
    from the SCAC (deterministic — no Faker/wall-clock).
    """
    snapshot = pd.DataFrame(
        {
            "scac": list(CARRIER_SCACS),
            "carrier_name": [f"Carrier {scac}" for scac in CARRIER_SCACS],
        }
    )
    fresh = _build_scd2_snapshot(
        snapshot, "scac", _CARRIER_TRACKED, run_date, provenance="synthetic"
    )
    if existing is None:
        return fresh
    return _apply_scd2_reload(existing, fresh, "scac", run_date)


# --------------------------------------------------------------------------- #
# Synthetic vessel -> carrier operated_by assignment (D-09)
# --------------------------------------------------------------------------- #
def assign_operated_by(vessel_imos: list[str]) -> pd.DataFrame:
    """Deterministically assign each vessel a carrier SCAC (synthetic, D-09).

    AIS has no operator field, so the vessel->carrier edge is reference-assigned
    via a seeded RNG (numpy default_rng(SEED + OPERATED_BY_OFFSET); numpy pinned
    EXACT 1.26.4 — do not bump). Every row carries provenance="synthetic" (D-11).
    Iterates vessel_imos in their given order so output is byte-stable.
    """
    rng = np.random.default_rng(SEED + OPERATED_BY_OFFSET)
    scacs = list(CARRIER_SCACS)
    rows = [
        {
            "vessel_imo": imo,
            "carrier_scac": scacs[int(rng.integers(0, len(scacs)))],
            "provenance": "synthetic",
        }
        for imo in vessel_imos
    ]
    return pd.DataFrame(rows, columns=["vessel_imo", "carrier_scac", "provenance"])


# --------------------------------------------------------------------------- #
# WPI centroid sanity assertion (Pitfall 6 / threat T-04-06)
# --------------------------------------------------------------------------- #
def assert_centroids_in_bbox(wpi: pd.DataFrame) -> None:
    """Fail loud if a target port's WPI centroid is outside its PORT_BBOXES box.

    For each of USHOU/USLAX/USNYC/USSAV present in ``wpi``, assert its (lat, lon)
    centroid falls inside the Phase-3 bounding box (lon_min, lon_max, lat_min,
    lat_max). A DMS / wrong-sign value lands the fence in the wrong hemisphere and
    is caught here BEFORE derivation (Pitfall 6 / V5 input validation). Raises
    ValueError naming the offending port code.
    """
    if not {"unlocode", "lat", "lon"}.issubset(wpi.columns):
        raise ValueError(
            "centroid sanity needs 'unlocode','lat','lon' columns (Pitfall 6)."
        )
    by_code = {row["unlocode"]: (row["lat"], row["lon"]) for _, row in wpi.iterrows()}
    for code, (lon_min, lon_max, lat_min, lat_max) in PORT_BBOXES.items():
        if code not in by_code:
            continue  # not every WPI subset carries all four target ports
        lat, lon = by_code[code]
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            raise ValueError(
                f"WPI centroid for {code} (lat={lat}, lon={lon}) falls OUTSIDE its "
                f"PORT_BBOXES box (lon {lon_min}..{lon_max}, lat {lat_min}..{lat_max}) "
                "— likely a DMS/sign coordinate-format error (Pitfall 6 / T-04-06)."
            )
