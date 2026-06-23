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

export interface Uc3Envelope {
  closure_gibraltar: Uc3ClosureGibraltar;
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

/** A UC4 path hop enriched with resolved coords. */
export type Uc4PathHopEnriched = Uc4PathHop & {
  lat: number;
  lon: number;
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
export type Uc4Enriched = Omit<Uc4Envelope, "baseline_path" | "reroute_path"> & {
  baseline_path: Uc4PathHopEnriched[];
  reroute_path: Uc4PathHopEnriched[];
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
