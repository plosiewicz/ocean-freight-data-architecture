# M1 Deck Source — Real vs. Synthetic Data Strategy (DOM-04)

> **Manual step:** This file is the repo-side source of truth. Placing this content onto the M1 "Real vs. Synthetic" slide in the shared Google Slides deck is a manual copy-paste step — do not create a new deck.

## The defended three-tier strategy (D-15)

The architecture splits data into three tiers by provenance and role. Real data grounds the model; synthetic data fills the forwarder-internal gaps the public data cannot supply; real priors *condition* the synthetic data so the fabricated network is realistic rather than arbitrary.

### Tier 1 — REAL ground truth (loaded as facts/reference)

- **AIS positions** (MarineCadastre) → derived **port-calls** and **voyage-legs**.
- **Port reference** — **World Port Index (NGA)** attributes + lat/lon, keyed to **UN/LOCODE** (the canonical conformed key).
- **Vessel reference** (IMO natural key; MMSI as the AIS join key).
- **Chokepoint nodes** (Suez, Panama, Malacca) for the network/reachability use cases.

### Tier 2 — REAL priors only (conditioners, NOT loaded as facts)

These are real public indices used as **weights/conditioners** on the synthetic network — never stored as transactional facts:

- **UNCTAD LSCI** → which port-pairs *plausibly* carry liner service, plus a frequency weight.
- **UN Comtrade O-D** → booking-volume weight by trade lane (reporter→partner demand).
- **World Bank LPI** → baseline reliability / delay distribution by country.

### Tier 3 — SYNTHETIC (fabricated, deterministically generated)

- Bookings.
- Container / shipment events.
- Proforma schedules.
- Vessel→carrier operator assignments (AIS carries no operator field).
- Lane structure beyond what AIS directly observes.

## Provenance commitment (D-14)

**Every record carries a `real | synthetic` flag** from landing, through the Silver conformance layer, into the demo. This lets the demo honestly distinguish grounded data from generated data at the row level, and it matches the Phase 4 success criterion.

## Scale grounding (D-12)

Synthetic volume is **scaled to the observed real AIS port-call count** over the bounded quarter, so the synthetic-to-real ratio is grounded in real vessel movement rather than picked arbitrarily. Rough order of magnitude: **thousands of bookings and tens of thousands of container events**. This gives the M3 pitch a concrete, defensible scale number tied to actual data.

## LSCI bilateral-gap framing nuance (D-13 / Research Pitfall 2)

There is **no free bilateral port-pair liner-service feed** — UNCTAD LSCI is published at country-level and per-port (Port-LSCI, >900 ports), not as a port-pair route table (that is proprietary, e.g. Alphaliner/MDS). Therefore port-pair plausibility is **DERIVED** by combining **Port-LSCI** (per-port connectivity weight) with **Comtrade O-D** (per-lane demand) to weight the synthetic edges.

This is a **defended design choice, not a gap**: D-13/D-15 already commit to using priors as *conditioners*, not facts. If a reviewer asks "where is your route table?", the answer is that there isn't a free one — the synthetic network is conditioned by real per-port and per-lane priors, which is precisely the point of the real↔synthetic split. (This also anticipates the Phase 2 MOD-08 gap analysis.)
