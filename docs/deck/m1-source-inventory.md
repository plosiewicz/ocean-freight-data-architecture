# M1 Source Inventory — DOM-03 Access Verification

> **Source content for the M1 "Source Inventory" deck slide.** Slide placement into the shared Google Slides deck is a manual step.
>
> **Team:** Grilled Cheesin · **Pull date:** 2026-06-13 · **Bar:** D-11 — "access verified" means a *real pull* with recorded row/byte evidence, not a list of URLs.

Each row below cites a sample artifact actually pulled to `samples/` (gitignored — proof-of-pull, never redistributed in bulk). All six sources are freely accessible for the bounded course slice.

## Source Inventory

| Source | Access URL / API | Format | Sample row count | Sample byte size | License / redistribution terms | Pull date | Confirmed required fields |
|--------|------------------|--------|------------------|------------------|--------------------------------|-----------|---------------------------|
| **MarineCadastre AIS** (NOAA/BOEM) | `https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2023/AIS_2023_01_01.zip` (canonical NOAA daily object; the Azure blob `ocmgeodatastor1.../marinecadastre/` container listing returned ResourceNotFound at pull time — see note e) | Daily national CSV in zip (national day = 8,156,509 rows / 877 MB uncompressed) | **80,278** rows after bounding filter (Houston/Galveston bbox + cargo `VesselType` 70–79 + tanker 80–89; 181 distinct MMSI) | **9,992,470** bytes (filtered sample; raw 319 MB zip / 877 MB CSV **not** retained) → `samples/ais_2023_01_01_houston_cargo_tanker_sample.csv` | **US-Gov public domain** (NOAA/BOEM) | 2026-06-13 | `VesselType`, `MMSI`, `LAT`, `LON`, `BaseDateTime` **all present**; `IMO` present — see note (a) |
| **World Port Index** (NGA Pub 150) | `https://msi.nga.mil/api/publications/download?type=view&key=...UpdatedPub150.csv` | CSV (109 columns) | **3,804** ports | **3,510,247** bytes → `samples/world_port_index_pub150.csv` | **US-Gov public domain** (NGA) | 2026-06-13 | `UN/LOCODE` (col 6), `Latitude` (108), `Longitude` (109), depth/harbor-type/facilities attributes — satisfies D-08; **A3 = YES**, see note (b) |
| **UN/LOCODE** (UNECE) | UNECE canonical `unece.org/trade/cefact/UNLOCODE-Download`; pulled via pre-split mirror `raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv` | CSV | **116,213** location rows | **7,287,475** bytes → `samples/unlocode_code-list.csv` | **UNECE terms** — cite UNECE as source of record; mirror for convenience | 2026-06-13 | LOCODE code columns `Country` + `Location` present (e.g. `AD`/`ALV`); `Coordinates`, `Function` also present |
| **UNCTAD LSCI** | World Bank Data360 `https://data360api.worldbank.org/data360/data?DATABASE_ID=UNCTAD_LSC` (mirrors UNCTADstat `US.LSCI`) | JSON (SDMX-style observations) | **200** observations pulled (of **11,875** available) | **139,212** bytes → `samples/unctad_lsci_data360_UNCTAD_LSC_sample.json` | **UNCTAD / World Bank terms-of-use** — cite, do not redistribute bulk | 2026-06-13 | `REF_AREA` (country), `INDICATOR` (`UNCTAD_LSC_INDEX`), `TIME_PERIOD` (quarterly, e.g. `2006-Q4`), `OBS_VALUE` — **country-level**, see note (d) |
| **World Bank LPI** | Indicator API `https://api.worldbank.org/v2/country/all/indicator/LP.LPI.OVRL.XQ?date=2023` | JSON | **266** country/aggregate records (LPI 2023) | **63,297** bytes → `samples/worldbank_lpi_LP.LPI.OVRL.XQ.json` | **World Bank terms-of-use** — cite, do not redistribute bulk | 2026-06-13 | `country`, `countryiso3code`, `date` (2023), `value` (overall LPI 1–5) — country-level reliability prior |
| **UN Comtrade** | Public preview REST `https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=842&period=2022&partnerCode=156,392,410,490&cmdCode=TOTAL&flowCode=M` | JSON | **4** O-D records (bounded query, well under the 100K free ceiling) | **3,638** bytes → `samples/comtrade_usa_imports_2022_sample.json` | **UN terms-of-use** — cite, do not redistribute bulk | 2026-06-13 | USA-imports-by-partner O-D values (China 156, Japan 392, S.Korea 410, Other Asia 490) — lane-demand prior. **No API key used/committed**, see note (c) |

## Notes

### (a) AIS IMO field — sparsity nuance (Pitfall 1)
Research flagged `IMO` as "present-but-sparse" because AIS broadcasts IMO only in Type-5 *static* messages, not in every position report. In the **filtered** sample this nuance partly washes out: because the filter keeps only **cargo + tanker** vessels (which reliably broadcast static messages), IMO was meaningfully populated for **98.5%** of the 80,278 sample rows. The sparsity concern still holds for the **unfiltered** national feed (small craft, fishing, passenger that omit IMO) and remains the basis for **D-09**: `MMSI` is the reliable AIS join key, `IMO` is the conformed natural key. IMO↔MMSI resolution is deferred to **Phase 4** (highest-risk per STATE.md) — not solved here, only the field's existence and the cargo/tanker coverage are confirmed.

### (b) Open Question A3 — does WPI carry UN/LOCODE directly? → **YES**
The NGA Pub 150 WPI CSV includes a dedicated `UN/LOCODE` column (column 6) alongside `Latitude`/`Longitude` and the depth/harbor-type/facilities attributes D-08 needs. **No name/coordinate join is required** to bridge WPI → conformed UN/LOCODE key. This resolves A3 (previously MEDIUM-risk) and de-risks the Phase-2 MOD-07 conformed-key strategy: WPI rows can be keyed on UN/LOCODE directly. (Caveat for Phase 2/3: some WPI rows may carry a blank UN/LOCODE and will need a coordinate/name fallback — column presence is confirmed; per-row completeness is a Phase-3 data-quality check.)

### (c) UN Comtrade — no key needed, no key committed (threat T-02-01 / DEL-02)
The bounded preview query succeeded against the **public** Comtrade endpoint **without** an API key. The plan reads any key from environment (`COMTRADE_API_KEY`) at run time only; **no API key or billing account ID appears in any committed file**, and `samples/` plus `.env`/`*.key`/`secrets.*` are gitignored (Task 1). The full O-D prior extract is a bounded **Phase-3** task designed to stay under the 100K-records/call free ceiling (Pitfall 3).

### (d) UNCTAD LSCI bilateral-port-pair gap (Pitfall 2)
LSCI is published at **country-level** (and Port-LSCI per-port) — there is **no free bilateral port-pair liner-service feed**. D-13 wants "which port-pairs carry liner service + frequency," which no free source provides directly. This is a **defended design choice, not a blocker**: per D-13/D-15, real indices are used as **priors/conditioners, not facts** — synthetic port-pair plausibility is *derived* by combining Port-LSCI (per-port connectivity weight) × Comtrade O-D (lane demand weight). This anticipates the Phase-2 MOD-08 gap analysis; the answer to "where is your route table?" is "there isn't a free one — the synthetic network is conditioned by real per-port and per-lane priors."

### (e) AIS access path note
The CLAUDE.md / research-cited Azure blob container (`ocmgeodatastor1.blob.core.windows.net/marinecadastre/ais<YEAR>/`) returned `ResourceNotFound` on container/prefix listing at pull time (layout appears to have drifted). The **canonical NOAA `coast.noaa.gov/htdata/CMSP/AISDataHandler/<YEAR>/AIS_<YEAR>_MM_DD.zip` object path** is the verified working access path and is what the inventory cites. Note for Phase 3: years 2024–2025 also offer experimental analysis-ready **GeoParquet** files that may be a smaller/cleaner ingest format than raw CSV.

### Bounded AIS slice envelope (D-04 / D-05 / D-06) and scale rationale (D-07)
- **D-04 — Geography:** 4 US container gateways across three coasts — LA/Long Beach (San Pedro Bay), NY/NJ, Savannah, Houston. (Verification sample used the Houston/Galveston box; the other three bboxes are a Phase-3 detail.)
- **D-05 — Time window:** one recent complete quarter (~3 months). **Exact quarter is deferred to Phase-3 sourcing** — pinned against MarineCadastre availability then. Phase-1 verification used a single day (2023-01-01) purely to prove the pull path; it does not commit the quarter.
- **D-06 — Landing downsampling:** filter to cargo + tanker `VesselType`, thin positions to ~5-minute cadence, keep only points inside port-region bounding boxes + approach lanes.
- **D-07 — Defensible scale story:** This bound keeps the slice within the **$50/mo GCP budget** and the **ArangoDB CE 100 GiB cap** while still exercising partitioning, multi-port comparison (UC2), and temporal trends (UC1). A single national AIS day is already 8.16M rows / 877 MB uncompressed; the bounded 4-port cargo/tanker slice for a quarter is a small, defensible fraction. **Full global *real* AIS is explicitly out of scope.**

### Real ↔ synthetic provenance (cross-reference)
Source-tier classification (real ground truth vs. real priors vs. synthetic) is documented in `docs/deck/m1-real-vs-synthetic.md` (DOM-04). In short: AIS + WPI + UN/LOCODE are **real ground truth**; LSCI + LPI + Comtrade are **real priors only**; bookings/container-events/carrier-assignments are **synthetic**.

---

*DOM-03 satisfied: all six sources access-verified by real pull with recorded row/byte evidence; AIS required fields confirmed; A3 answered (YES), exact-quarter deferred to Phase 3, LSCI bilateral-gap framed; no secrets or bulk data committed.*
