// Source-of-truth types for the four golden response envelopes (DATA-01 contract).
// These mirror web/server-assets/golden/uc{1..4}.golden.json field-for-field, so the
// live BigQuery/ArangoDB handlers in Phases 11/12 are obligated to produce the SAME
// shape — the contract IS the golden shape (D-08).
//
// Provenance/store caveat: the UC1/UC2 golden carry a top-level `store` whose value is
// the LOWERCASE string "bigquery". UC3/UC4 golden have NO top-level `store` key at all.
// The provenance UI must therefore source its displayed store from web/lib/use-cases.ts
// (the typed source of truth), never from these `store` strings — and these types must
// not assume a store field is present everywhere.

/** Which path actually served the response: the frozen snapshot or a live store query. */
export type ServedBy = "golden" | "live";

// ---- UC1: ETA reliability & delay drivers (BigQuery / OLAP) ----

export interface Uc1Row {
  carrier_name: string;
  carrier_scac: string;
  origin_unlocode: string;
  dest_unlocode: string;
  lane_key: string;
  legs: number;
  on_time_pct: number;
  avg_delay_hours: number;
}

export interface Uc1Envelope {
  frozen_at_iso: string;
  query: string;
  row_count: number;
  rows: Uc1Row[];
  store: string; // golden value is lowercase "bigquery"
  use_case: string;
}

// ---- UC2: Port dwell & turnaround trend (BigQuery / OLAP) ----

export interface Uc2Row {
  unlocode: string;
  call_date: string;
  calls: number;
  avg_turnaround_hours: number;
  max_turnaround_hours: number;
}

export interface Uc2Envelope {
  frozen_at_iso: string;
  query: string;
  row_count: number;
  rows: Uc2Row[];
  distinct_call_dates: number;
  store: string; // golden value is lowercase "bigquery"
  use_case: string;
}

// ---- UC3: Chokepoint risk exposure (ArangoDB / graph) — NO top-level store key ----

export interface Uc3ClosureGibraltar {
  closed: string;
  closed_origins: number;
  closed_reachable_total: number;
  open_origins: number;
  open_reachable_total: number;
}

export interface Uc3TransitShare {
  chokepoint: string;
  total_lanes: number;
  transit_share_pct: number;
  transiting_lanes: number;
}

export interface Uc3RerouteImpactSuez {
  baseline_hours: number;
  baseline_legs: number[];
  reroute_hours: number;
  reroute_legs: number[];
  delta: number;
  disabled_lanes: string[];
  origin: string;
  dest: string;
  closed: string;
}

/**
 * A baked sea-route polyline point, in deck.gl/golden [lon, lat] order (REQ-14-4).
 * These coords are PRE-COMPUTED by analytics/lib/searoute_geometry.polyline_for and
 * baked into the golden — they are passed through verbatim, never re-derived at
 * runtime (CSP: no client-side geometry computation, no external searoute call).
 */
export type Uc4Waypoint = [number, number];

/**
 * One disabled lane's baked polyline (REQ-14-2/4): the lane key (e.g. "USNYC__CNSHA")
 * plus the per-lane sea-route waypoints routed THROUGH the closed chokepoint.
 */
export interface Uc3DisabledLanePath {
  lane_key: string;
  waypoints: Uc4Waypoint[];
}

/**
 * One per-chokepoint closure + reroute-impact entry (the 7-chokepoint generalization
 * of closure_gibraltar + reroute_impact_suez). Carries ONLY counts/floats/strings —
 * disabled_lane_COUNT, never the lane list or any credential material (T-lwx-02).
 */
export interface Uc3ClosureEntry {
  chokepoint: string;
  open_reachable_total: number;
  closed_reachable_total: number;
  open_origins: number;
  closed_origins: number;
  reroute_baseline_hours: number;
  reroute_reroute_hours: number;
  reroute_delta_hours: number;
  disabled_lane_count: number;
  // REQ-14-2 (additive): the actual disabled-lane KEYS for the closed chokepoint, so
  // the map can highlight the affected lanes (not just the count). Pure geometry/keys —
  // no credential material (T-14-09).
  disabled_lanes: string[];
  // REQ-14-4 (additive): one baked cosmetic sea-route polyline per disabled lane.
  disabled_lane_paths: Uc3DisabledLanePath[];
}

export interface Uc3Envelope {
  closure_gibraltar: Uc3ClosureGibraltar;
  closure_by_chokepoint: Uc3ClosureEntry[];
  transit_share: Uc3TransitShare[];
  reroute_impact_suez: Uc3RerouteImpactSuez;
  origin: string;
  dest: string;
  frozen_at_iso: string;
  use_case: string;
  // NOTE: intentionally NO `store` field — UC3 golden has none.
}

// ---- UC4: Disruption rerouting (ArangoDB / graph) — NO top-level store key ----

export interface Uc4PathHop {
  port: string;
  leg_hours: number;
  // REQ-14-4 (additive): the baked per-hop sea-route polyline ([lon,lat] points) for
  // the leg ARRIVING at this hop. Optional so legacy hop-only data stays valid; when
  // present it is passed through verbatim (CSP: never re-derived at runtime).
  waypoints?: Uc4Waypoint[];
}

/**
 * One curated UC4 disruption scenario (REQ-14-6 / DECISION 3): closes ONE named
 * chokepoint and carries its baseline-vs-reroute paths with per-hop baked waypoints.
 *
 * Fragmentation-aware (PROJECT D-12, user-approved Option A): a `fragmenting` scenario
 * (GIBRALTAR) has NO model reroute — `reroute_available: false`, empty `reroute_path`,
 * `delta: 0`, but keeps cosmetic baseline geometry to render. Non-fragmenting scenarios
 * (SUEZ/PANAMA) carry a strict positive reroute `delta`. The scenario selector + label
 * must handle BOTH: render the `closed` label + baseline + geometry for a scenario with
 * no positive reroute, never assuming a reroute path exists.
 */
export interface Uc4Scenario {
  id: string;
  label: string;
  closed: string;
  origin: string;
  dest: string;
  fragmenting: boolean;
  reroute_available: boolean;
  disabled_lanes: string[];
  baseline_path: Uc4PathHop[];
  reroute_path: Uc4PathHop[];
  baseline_hours: number;
  reroute_hours: number;
  delta: number;
}

export interface Uc4Envelope {
  baseline_path: Uc4PathHop[];
  reroute_path: Uc4PathHop[];
  baseline_hours: number;
  reroute_hours: number;
  delta: number;
  disabled_lanes: string[];
  origin: string;
  dest: string;
  frozen_at_iso: string;
  use_case: string;
  // REQ-14-6 (additive): curated scenarios behind the selector. Each closes a named
  // chokepoint with baked geometry; the legacy top-level fields above MIRROR
  // scenarios[0] verbatim (Assumption A4 — legacy downstream contract unchanged).
  scenarios?: Uc4Scenario[];
  // NOTE: intentionally NO `store` field — UC4 golden has none.
}

// ---- DATA-07 coordinate-enriched variants (Phase 10) ----
//
// The base Uc3Envelope/Uc4Envelope above mirror the golden JSON field-for-field
// and ARE the P11/P12 contract — they are deliberately NOT mutated here. The
// enriched variants ADD server-joined geography (lat/lon, and for chokepoints a
// display `name`) that web/lib/coords.ts populates at the serve() seam. The
// enriched coords are PRESENT (not optional): the join drops any element whose
// coord fails to resolve, so a value that survives into these types always has a
// finite coord (never null island).

/** A finite WGS84 coordinate. */
export interface Coord {
  lat: number;
  lon: number;
}

/**
 * A transit_share chokepoint enriched with its display name (from chokepoints.csv,
 * e.g. "Strait of Gibraltar") and resolved coords. `name` is REQUIRED — UC3 tooltips
 * and the closure label read the display name, never the raw key (BLOCKER 2).
 */
export type Uc3TransitShareEnriched = Uc3TransitShare & {
  name: string;
  lat: number;
  lon: number;
};

/**
 * The single typed home for UC3 port coords (WARNING 4): the explicit derived
 * port set (origin+dest+disabled_lanes), each with finite coords. NOT loosely
 * attached to reroute_impact_suez.
 */
export interface Uc3PortEnriched {
  unlocode: string;
  lat: number;
  lon: number;
}

/** A UC4 path hop enriched with resolved coords (carries optional baked waypoints). */
export type Uc4PathHopEnriched = Uc4PathHop & {
  lat: number;
  lon: number;
};

/**
 * A curated UC4 scenario enriched with coord-bearing hops (REQ-14-6). Mirrors the
 * envelope-level enrichment: both path arrays replaced by the coord-bearing hop
 * variant. `waypoints` pass through verbatim on each hop (already [lon,lat]).
 */
export type Uc4ScenarioEnriched = Omit<
  Uc4Scenario,
  "baseline_path" | "reroute_path"
> & {
  baseline_path: Uc4PathHopEnriched[];
  reroute_path: Uc4PathHopEnriched[];
};

/**
 * The enriched UC3 envelope the map renders against: the base envelope with
 * `transit_share` replaced by the name+coord-bearing variant, plus a NEW explicit
 * `ports[]`. Carries `served_by` (added by serve()).
 */
export type Uc3Enriched = Omit<Uc3Envelope, "transit_share"> & {
  transit_share: Uc3TransitShareEnriched[];
  ports: Uc3PortEnriched[];
};

/**
 * The enriched UC4 envelope: base envelope with both path arrays replaced by the
 * coord-bearing hop variant. Carries `served_by` (added by serve()).
 */
export type Uc4Enriched = Omit<
  Uc4Envelope,
  "baseline_path" | "reroute_path" | "scenarios"
> & {
  baseline_path: Uc4PathHopEnriched[];
  reroute_path: Uc4PathHopEnriched[];
  // REQ-14-6: the curated scenarios with coord-enriched hops. Optional so a legacy
  // (pre-14-04) envelope without scenarios still type-checks.
  scenarios?: Uc4ScenarioEnriched[];
};

/** Map a uc id to its envelope type for the generic serve() call site. */
export interface EnvelopeByUc {
  uc1: Uc1Envelope;
  uc2: Uc2Envelope;
  uc3: Uc3Envelope;
  uc4: Uc4Envelope;
}

/** The four use-case ids the golden loader / serve() accept. */
export type UcId = keyof EnvelopeByUc;
