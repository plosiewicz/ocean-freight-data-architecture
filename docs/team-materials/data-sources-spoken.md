# Data Sources — Plain-English Companion

> **Team Grilled Cheesin · MSDS 683.** A spoken-English companion to the technical
> `datasets.md`. Use this when explaining *out loud* where our data comes from, what it
> is, and how we got it. Authoritative facts live in `datasets.md` (provenance),
> `ingest/pull_ais.py` / `ingest/pull_priors.py` / `ingest/pull_reference.py` (retrieval),
> and `silver/identity.py` (vessel-identity resolution). This file just frames them for a
> human listener.

---

## First: what is an "economic prior"?

A **prior** (short for "prior belief") is a statistics term for *an assumption you bring
to the table before you generate or observe anything* — the starting knowledge that
shapes what you produce.

Our synthetic data (bookings, schedules, container moves) has to be **invented** — but if
we invent it randomly, it's worthless: ships sailing routes nobody ships on, delays that
don't match reality. So instead of inventing blindly, we **condition** the generator on
real-world economic facts. Those real facts are the "priors."

They're called **economic** because all three are real economic/trade indicators:

- **LSCI** (Liner Shipping Connectivity Index) — *how well-connected is each country to
  global shipping?* → decides **which routes plausibly exist**.
- **Comtrade** (trade flows) — *how much actual trade value moves from country A to
  country B?* → decides **how many bookings a lane gets** (busy trade lanes get more cargo).
- **LPI** (Logistics Performance Index, scored 1–5) — *how reliable is a country's
  logistics?* → decides **how much delay to inject** (low LPI → longer, more variable delays).

The pipeline formula `lane_weight = LSCI × LSCI × Comtrade` literally means *"a route is
plausible and busy in proportion to how connected both ends are and how much they actually
trade."* **The priors are never stored as rows** — they're only used as weights during
generation, then discarded. That's the key distinction from Tier-1 data.

**Defense line:** *"Our synthetic data isn't arbitrary — it's conditioned on real shipping
connectivity, real trade volumes, and real logistics-reliability scores, so the fabricated
network behaves like the real world."*

---

## The full data-source table

| # | Source | What it is (spoken English) | Tier / Role | How it's used | How we got it |
|---|--------|-----------------------------|-------------|---------------|---------------|
| 1 | **MarineCadastre AIS** (NOAA/BOEM) | Ships constantly broadcast their position, ID, and type over radio. This is that feed — the raw record of where vessels actually were. | **Tier 1 — Real ground truth.** The signal everything is derived from. | Geofenced into **port-calls** and **voyage-legs** → `fact_port_call`, `fact_voyage_leg`. MMSI→IMO resolved here so we know which *vessel* went where. | **File download** (not an API): one **GeoParquet** file per day, by constructed filename, from MarineCadastre's **Azure blob store**. US-Gov public domain. |
| 2 | **World Port Index** (NGA Pub 150) | A global directory of ~3,800 ports — coordinates, depths, harbor type, facilities. | **Tier 1 — Real reference.** | Builds `dim_port` and the graph's `ports` vertices. | **File download** from an NGA URL; **falls back to a committed sample** when NGA's firewall (WAF) blocks the automated fetch. |
| 3 | **UN/LOCODE** (UNECE) | The canonical registry of location codes (~116K) — e.g. `USHOU` = Houston. The shared "primary key" for places. | **Tier 1 — Conformed-key backbone.** | The natural key that joins the BigQuery warehouse and the ArangoDB graph 1:1. | **File download** (CSV) from a **GitHub mirror** of UNECE, for stability. |
| 4 | **Chokepoint nodes** | The 7 maritime chokepoints (Suez, Panama, Malacca, Gibraltar, Bab-el-Mandeb, Hormuz, Cape of Good Hope). | **Tier 1 — Real reference** (factual, but built by hand). | Graph `chokepoint` vertices + `transits_chokepoint` edges → powers UC3/UC4 (closure-impact, rerouting). | **Hand-authored** local file `reference/chokepoints.csv` — no free node-level feed exists, so we built it and sanity-checked coordinates. |
| 5 | **UNCTAD LSCI** | Liner Shipping Connectivity Index — how plugged-in each country is to global container shipping. | **Tier 2 — Economic prior (conditioner only).** Never stored as facts. | Weights **which port-pairs plausibly carry service**. | **REST API** (JSON), keyless — World Bank **Data360** endpoint. |
| 6 | **UN Comtrade** | Origin→destination trade-flow values: how much trade actually moves between countries. | **Tier 2 — Economic prior.** Conditioner only. | Weights **booking volume / lane demand** — busy lanes get more synthetic cargo. | **REST API** (JSON), keyless public preview; optional `COMTRADE_API_KEY` read from env only, never committed. |
| 7 | **World Bank LPI** | Logistics Performance Index — each country's logistics reliability scored 1–5. | **Tier 2 — Economic prior.** Conditioner only. | Sets the **delay distribution** for synthetic events (low LPI → longer, more variable delays). | **REST API** (JSON), keyless — World Bank Indicator API. |
| 8 | **Proforma schedules** | Published sailing schedules a forwarder would work from (52 lanes). | **Tier 3 — Synthetic.** | Lanes weighted by `LSCI × LSCI × Comtrade`; gives `schedule_delta` a baseline to measure delay against. | **Generated** deterministically (seeded NumPy + Faker). |
| 9 | **Bookings** | The forwarder's cargo bookings (20,000). | **Tier 3 — Synthetic.** | Commercial layer on top of real vessel movement. | **Generated** — booking refs via seeded Faker. |
| 10 | **Container events** | Shipment/container movement events (200,000). | **Tier 3 — Synthetic.** | Feeds `fact_container_event`; delays drawn from the **LPI-conditioned** lognormal. | **Generated** — seeded NumPy. |
| 11 | **Vessel→carrier assignments** | Which carrier operates which vessel (1,545 vessels → 8 carriers). | **Tier 3 — Synthetic.** | The `operated_by` bridge — AIS has **no operator field**, so this link must be invented. | **Derived in Silver** from a seeded assignment. |

---

## The three-sentence summary

- **Tier 1 (rows 1–4)** is **real data that becomes actual facts/reference** — mostly
  **file downloads**, plus one hand-authored reference file.
- **Tier 2 (rows 5–7)** is the **economic priors** — **real REST APIs** returning JSON,
  used only as **weights** to make the synthetic data realistic, then thrown away (never stored).
- **Tier 3 (rows 8–11)** is **synthetic** — deterministically generated to fill the
  forwarder's private internal data that no public source provides.

Every Tier-1 and Tier-3 row that lands carries a **`real | synthetic` provenance flag**, so
the demo never blurs the line between grounded and generated data.

## Q&A one-liner (download vs API vs hand-authored)

> "The AIS is a direct GeoParquet file download per day from MarineCadastre's Azure store.
> The three real economic priors — LSCI, LPI, and Comtrade — come in over public REST APIs
> as JSON, keyless. Port and location reference data are file downloads with committed-sample
> fallbacks, and the chokepoints are hand-authored. The MMSI→IMO resolution runs on the AIS
> data, and that's what gives us reliable 'which vessel went where.'"
