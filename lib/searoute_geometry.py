"""Deterministic, offline, byte-stable sea-route polyline precompute (REQ-14-4).

REQ-14-4 (real sea-route geometry baked into the golden) needs a deterministic,
offline, byte-stable polyline source so the snapshot/freeze layer (Plan 04) can
bake real maritime polylines and the web render layer (Plan 05) can draw them with
deck.gl ``PathLayer`` / ``TripsLayer``. This module is that source.

GUARANTEES
  * Deterministic — ``searoute`` is a pure NetworkX shortest-path over a bundled
    maritime graph (the "marnet"); it has NO RNG, so identical
    ``(origin, dest, restrict)`` input yields byte-identical coordinate output.
    [VERIFIED empirically — 14-RESEARCH.md Pattern 1 / Pitfall 1.]
  * Byte-stable — every emitted coordinate is pre-rounded to 12 decimal places
    (helper mirroring ``scripts/freeze_uc._round_floats``) so a re-freeze stays
    byte-identical and ``freeze_uc._round_floats`` is a no-op over this output.
  * OFFLINE-ONLY — ``import searoute`` runs only here, at generate/freeze time.
    This module is NEVER imported by ``web/`` and is NEVER called at runtime
    (the web app is CSP-restricted; geometry is precomputed and baked, not
    computed on request). Geometry is COSMETIC: the analytic
    ``transit_time_hours`` / ``delta`` math stays on the existing haversine/18kn
    weights and never adopts searoute's distance/duration.

DELIBERATELY DELEGATED to searoute (the inverse of ``silver/haversine.py``'s
"deliberately hand-rolled" note): a coastline-aware maritime routing graph that
forces a route through/around a named canal is exactly what searoute bundles
(10 MB marnet); rebuilding it would be weeks of error-prone work around the
straits (14-RESEARCH.md § Don't Hand-Roll). The only net-new dependency this
phase adds is searoute.

ANTIMERIDIAN CONVENTION (chosen + documented — Option B, RESEARCH Pitfall 1):
  searoute keeps a CONTINUOUS (un-wrapped) line across the date line, so a
  westbound Asia<->USEC route emits longitudes well outside [-180, 180]
  (e.g. Shanghai as 121.47 - 360 = -238.53). We normalize EVERY longitude into
  [-180, 180] via ``((lon + 180) % 360) - 180`` before baking. This makes the
  polyline endpoints coincide exactly with the stored port-marker coordinates
  (no 360-degree disagreement) and keeps every baked coordinate on-canvas. The
  tradeoff (vs Option A's continuous coords) is that a path crossing the date
  line can draw a horizontal seam streak in deck.gl unless the render layer
  splits it at the seam — handled downstream in Plan 05, NOT here.

RESTRICTION SEMANTICS (searoute AVOIDS the named passages):
  * to FORCE a route THROUGH Suez   -> ``restrict=("panama",)``
  * to FORCE a route THROUGH Panama -> ``restrict=("suez",)``
  * to FORCE a route AROUND the Cape -> ``restrict=("panama", "suez")``
  ``"northwest"`` is ALWAYS prepended so the Northwest Passage is never used
  (searoute's default convention; RESEARCH Pattern 1).

Provenance: searoute README (github.com/genthalili/searoute-py, 1.6.0,
Apache-2.0) + the empirical determinism/Suez/Panama/Cape run recorded in
14-RESEARCH.md (Pattern 1, Pitfall 1, Pitfall 2). Foreign-port centroids reuse
``lib.graph_loader._PORT_CENTROID_FALLBACK`` (the single offline coord source of
truth — this module introduces NO second coord table).
"""

from __future__ import annotations

# OFFLINE-ONLY: searoute is imported here, at generate/freeze time only. This
# module is never imported by web/ and never called at runtime (CSP-restricted).
import searoute as sr

# Single offline coord source of truth for foreign ports (no second table).
from lib.graph_loader import _PORT_CENTROID_FALLBACK

# searoute always keeps the Northwest Passage out of consideration.
_ALWAYS_RESTRICT: tuple[str, ...] = ("northwest",)

# Byte-stability contract: match scripts/freeze_uc._round_floats (12 places).
_ROUND_PLACES = 12

LonLat = list  # an emitted [lon, lat] pair


def _round_coord(value: float) -> float:
    """Round one coordinate component to 12 places (freeze_uc byte-stable contract)."""
    return round(float(value), _ROUND_PLACES)


def _normalize_lon(coord) -> list[float]:
    """Normalize one [lon, lat] into the documented Option-B range and 12-place round.

    Longitude is wrapped into [-180, 180] via ``((lon + 180) % 360) - 180`` so the
    continuous (antimeridian-crossing) line searoute emits lands on-canvas and its
    endpoints coincide with the stored port markers. Both components are then
    pre-rounded to 12 places so the freeze stays byte-identical.
    """
    lon, lat = float(coord[0]), float(coord[1])
    lon = ((lon + 180.0) % 360.0) - 180.0
    return [_round_coord(lon), _round_coord(lat)]


def centroid_for(port_code: str) -> list[float]:
    """Return the offline ``[lon, lat]`` centroid for a port code (lon-first).

    Reads ``lib.graph_loader._PORT_CENTROID_FALLBACK`` (which stores ``(lat, lon)``)
    and returns it lon-first to match searoute's input order. This is the single
    offline coord source — no second coord table is introduced here.
    """
    lat, lon = _PORT_CENTROID_FALLBACK[port_code]
    return [float(lon), float(lat)]


def polyline_for(origin, dest, restrict: tuple[str, ...] = ()) -> list[list[float]]:
    """Deterministic offline sea-route polyline between two ``[lon, lat]`` points.

    Args:
        origin: ``[lon, lat]`` origin (lon-first, searoute order).
        dest:   ``[lon, lat]`` destination (lon-first).
        restrict: passages to AVOID. ``("panama",)`` forces Suez; ``("suez",)``
            forces Panama; ``("panama", "suez")`` forces around the Cape.
            ``"northwest"`` is always added implicitly.

    Returns:
        A non-empty list of ``[lon, lat]`` pairs, every longitude normalized into
        [-180, 180] and every component pre-rounded to 12 places. Deterministic
        and byte-stable for the same input.
    """
    route = sr.searoute(
        origin,
        dest,  # [lon, lat] order (lon first)
        units="naut",
        restrictions=list(_ALWAYS_RESTRICT + tuple(restrict)),
        append_orig_dest=True,  # snap the true endpoints onto the line
    )
    coords = route["geometry"]["coordinates"]  # list of [lon, lat]
    return [_normalize_lon(c) for c in coords]
