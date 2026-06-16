# Datasets — Ocean Freight Forwarder Data Architecture

> **Team Grilled Cheesin · MSDS 683.** A single reference for every dataset feeding the pipeline: what it is, where it comes from, how it's licensed, and what role it plays. Authoritative source files: `docs/deck/m1-source-inventory.md` (access-verification evidence) and `docs/deck/m1-real-vs-synthetic.md` (provenance strategy).

## The three-tier provenance model

Every dataset belongs to exactly one tier. This split is the defended core of the design: **real data grounds the model, real priors condition the synthetic data so it's plausible rather than arbitrary, and synthetic data fills the forwarder-internal gaps public data can't supply.** Every Silver/Gold row carries a `real | synthetic` provenance flag from landing through the demo.

| Tier | Role | Datasets |
|------|------|----------|
| **1 — Real ground truth** | Loaded as facts / reference | AIS positions, World Port Index, UN/LOCODE, chokepoint nodes |
| **2 — Real priors** | Conditioners / weights only — **never stored as facts** | UNCTAD LSCI, UN Comtrade O-D, World Bank LPI |
| **3 — Synthetic** | Deterministically generated forwarder-internal data | Proforma schedules, bookings, container events, vessel→carrier assignments |

---

## Tier 1 — Real ground truth

### MarineCadastre AIS (NOAA / BOEM)
- **What it is:** Vessel position broadcasts (lat/lon, timestamp, MMSI, IMO, vessel type) — the raw signal from which we derive port-calls and voyage-legs.
- **Access:** `https://coast.noaa.gov/htdata/CMSP/AISDataHandler/<YEAR>/AIS_<YEAR>_MM_DD.zip` (verified canonical daily object). 2024–2025 also offer analysis-ready **GeoParquet**, which we ingest in preference to raw CSV.
- **Format:** GeoParquet (source format preserved into Bronze, WKB geometry).
- **Scale & bounding:** A single national day is ~8.16M rows / 877 MB uncompressed. We bound to a **defensible slice**: 4 US container gateways (LA/Long Beach, NY/NJ, Savannah, Houston), cargo + tanker vessel types (70–89), thinned to ~5-minute cadence, inside port bounding boxes. The landed slice is **~1.88M rows over a 31-day window**.
- **License:** US-Gov public domain (NOAA/BOEM).
- **Key fields:** `MMSI`, `IMO`, `LAT`, `LON`, `BaseDateTime`, `VesselType`. **`MMSI` is the reliable AIS join key; `IMO` is the conformed natural key** (IMO is broadcast only in Type-5 static messages — ~98.5% coverage in the cargo/tanker filter, sparse in the unfiltered feed). MMSI↔IMO resolution is handled in Silver (Phase 4).
- **Used by:** `fact_port_call`, `fact_voyage_leg` (derived via geofences, **not** from AIS free-text destination strings).

### World Port Index — NGA Pub 150
- **What it is:** Global port reference — coordinates, depths, harbor type, facilities (109 columns, ~3,800 ports).
- **Access:** `https://msi.nga.mil/api/publications/download?type=view&key=...UpdatedPub150.csv`
- **Format:** CSV.
- **License:** US-Gov public domain (NGA).
- **Key fields:** **`UN/LOCODE` (column 6 — carried directly, no name/coordinate join needed)**, `Latitude` (108), `Longitude` (109), depth/harbor-type/facilities. Some rows may carry a blank UN/LOCODE (coordinate/name fallback handled in Silver).
- **Used by:** `dim_port` and the ArangoDB `ports` vertex collection.

### UN/LOCODE (UNECE)
- **What it is:** The canonical location-code registry (~116K locations) — the conformed key backbone for ports and lanes.
- **Access:** UNECE is the source of record (`unece.org/trade/cefact/UNLOCODE-Download`); pulled via the pre-split mirror `raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv`.
- **Format:** CSV.
- **License:** UNECE terms — cite UNECE as source of record; mirror used for convenience.
- **Key fields:** `Country` + `Location` (e.g. `US` / `HOU`), `Coordinates`, `Function`.
- **Used by:** conformed-key strategy bridging warehouse (`dim_port` natural key) and graph (`_key`).

### Chokepoint nodes (hand-authored)
- **What it is:** A 7-node reference set of maritime chokepoints for the network / reachability use cases (UC3/UC4). Coordinates human-sanity-checked at M1.
- **Source:** `reference/chokepoints.csv` (hand-authored — no free node-level feed exists).
- **Nodes:** Suez Canal, Panama Canal, Strait of Malacca, Strait of Gibraltar, Bab-el-Mandeb, Strait of Hormuz, Cape of Good Hope.
- **Used by:** ArangoDB `chokepoint` vertices + `transits_chokepoint` edges.

---

## Tier 2 — Real priors (conditioners only)

> These are real public indices used as **weights** on the synthetic network. They are **never loaded as transactional facts.** Their job is to make the fabricated network realistic.

### UNCTAD LSCI (Liner Shipping Connectivity Index)
- **What it is:** Per-country (and per-port) liner-shipping connectivity index — used to weight which port-pairs *plausibly* carry liner service.
- **Access:** World Bank Data360 `https://data360api.worldbank.org/data360/data?DATABASE_ID=UNCTAD_LSC` (mirrors UNCTADstat `US.LSCI`, keyless).
- **Format:** JSON (SDMX-style observations).
- **Landed:** `data/priors/lsci/lsci.json` (~6.1 MB).
- **License:** UNCTAD / World Bank terms — cite, do not redistribute bulk.
- **Key fields:** `REF_AREA` (country), `INDICATOR`, `TIME_PERIOD` (quarterly), `OBS_VALUE`.
- **Known gap (defended):** LSCI is published at **country-level**, not as a bilateral port-pair route table — **no free port-pair liner-service feed exists** (proprietary: Alphaliner/MDS). Port-pair plausibility is therefore *derived* by combining Port-LSCI (per-port connectivity) × Comtrade O-D (lane demand). This is the answer to "where is your route table?" — there isn't a free one; the synthetic network is conditioned by real priors instead.

### UN Comtrade O-D (origin–destination trade flows)
- **What it is:** Trade-flow values by reporter→partner — used as the **booking-volume / lane-demand weight**.
- **Access:** Public preview REST `https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=842&period=2022&partnerCode=...&cmdCode=TOTAL&flowCode=M` (bounded well under the 100K-record free ceiling; **no API key used or committed** — read from `COMTRADE_API_KEY` env at runtime only).
- **Format:** JSON.
- **Landed:** `data/priors/comtrade/comtrade_od.json`.
- **License:** UN terms — cite, do not redistribute bulk.
- **Used by:** lane-weight conditioning of synthetic schedules/bookings (`lane_weight = LSCI × LSCI × Comtrade`).

### World Bank LPI (Logistics Performance Index)
- **What it is:** Per-country overall logistics-performance score (1–5) — used as the **baseline reliability / delay-distribution prior**.
- **Access:** Indicator API `https://api.worldbank.org/v2/country/all/indicator/LP.LPI.OVRL.XQ?date=2023`
- **Format:** JSON.
- **Landed:** `data/priors/lpi/lpi.json` (null aggregate records filtered).
- **License:** World Bank terms — cite, do not redistribute bulk.
- **Key fields:** `country`, `countryiso3code`, `date`, `value`.
- **Used by:** LPI-conditioned `numpy` lognormal delay distribution in synthetic event generation.

---

## Tier 3 — Synthetic (deterministically generated)

> Fills the forwarder-internal gaps public data cannot supply (bookings, container moves, schedules, carrier assignments). **Fully deterministic** — seeded `numpy.random.default_rng` + pinned `Faker` produce byte-identical output on re-run from a fresh clone (proven by committed `synthetic.sha256`). Volume is scaled to the observed real AIS port-call count, so the synthetic-to-real ratio is grounded in real vessel movement.

| Dataset | Landed file | Volume | Notes |
|---------|-------------|--------|-------|
| **Proforma schedules** | `data/synthetic/schedules.jsonl` | **52** | Lanes weighted by LSCI × LSCI × Comtrade; includes US→US proforma lanes so `schedule_delta` populates. |
| **Bookings** | `data/synthetic/bookings.jsonl` | **20,000** | Booking refs / identifiers via seeded Faker. |
| **Container events** | `data/synthetic/container_events.jsonl` | **200,000** | Shipment/container moves; delays drawn from LPI-conditioned lognormal. |
| **Vessel→carrier assignments** | (derived in Silver, `silver/operated_by`) | 1,545 vessels → 8 carriers | AIS carries no operator field; assignment is synthetic (`operated_by` bridge). |

**Determinism contract:** generators are pure (seed → files), loaders are idempotent (files → store). Central `SEED` + per-entity `seed_instance()`. Pinned for reproducibility: `Faker==40.1.2`, `numpy==1.26.4` (a deliberate deviation from the CLAUDE.md NumPy 2.x guidance, for output stability).

---

## How datasets flow through the medallion layers

```
Bronze (immutable, source-format)        Silver (conformed, single source of truth)      Gold
─────────────────────────────────       ────────────────────────────────────────       ──────────────────────
AIS GeoParquet ───────────────────────▶ geofence → port-calls / voyage-legs ──┬───────▶ BigQuery star (OLAP)
WPI / UN/LOCODE / chokepoints ────────▶ conformed dims (UN/LOCODE, IMO, SCAC) ─┤          fact_voyage_leg, fact_port_call
LSCI / Comtrade / LPI (priors) ───────▶ condition ─┐                          └───────▶ ArangoDB graph (network)
synthetic schedules/bookings/events ──▶ ───────────┘                                     ocean_network
```

Both Gold stores read from the **same conformed Silver layer** and never from each other — the shared business keys (UN/LOCODE, IMO, SCAC) are what let a graph result join 1:1 back to a BigQuery fact in the demo.

## Licensing / redistribution summary

| Dataset | License | Redistribution |
|---------|---------|----------------|
| AIS, WPI | US-Gov public domain | Free |
| UN/LOCODE | UNECE terms | Cite UNECE; mirror for convenience |
| LSCI, Comtrade, LPI | UNCTAD / UN / World Bank terms | Cite, **do not redistribute bulk** |
| Chokepoints, synthetic | Project-authored | Free (reproducible from clone) |

**No secrets or bulk data are committed.** Proof-of-pull samples live in `samples/` (gitignored); API keys are read from environment at runtime only.
