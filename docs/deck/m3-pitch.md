# M3 Deck Source — Midterm Design Pitch (DEL-03)

> **Manual step:** This file is the repo-side source of truth. Placing this content onto the M3 "Midterm Design Pitch" section of the shared Google Slides deck is a manual copy-paste step — do not create a new deck.
>
> **Purpose:** A ~7-min design-pitch brief distilled from the project brief and the repo source files in `docs/deck/` + `docs/team-materials/m3-pitch-talking-points.md`. Each section below maps to **one slide**. Copy the **Slide content** into the shared Google Slides deck; the **Defense / speaker notes** are what you say out loud or keep for Q&A.
>
> **Do not create a new deck** — all milestones live in the single shared deck (rubric rule).

---

## What M3 is grading (keep this in mind)

- **M3 — Midterm Design Pitch (~7 min + Q&A):** present the *design* — domain, analytical questions, processing paradigm (OLAP vs OLTP), schema (star vs snowflake), the transformation pipeline, and the tech stack — and *defend* the choices.
- The brief explicitly says *"you don't need to have built this yet."* We have one slice. So we present as **"here's the design, and here's the slice we already proved."**
- This design also seeds the **MSDS 681 Lakehouse** build next term — the architecture is **designed to extend** to a lakehouse (not built here).

---

# MILESTONE 3 — Midterm Design Pitch (5 slides, ~7 min)

## Slide M3-1 — Team, Domain & Business Goal *(~1 min)*

**Slide content**
- **Team:** Grilled Cheesin — P.J. Losiewicz · Borna Karimi · Alexander Mohun
- **Domain:** End-to-end data architecture for a **freight forwarder / 3PL** in **global ocean container logistics** — a logistics middleman that books cargo on ships it doesn't own.
- **Business goal:** **risk & reliability** — which routes/carriers are unreliable, where ports congest, and what happens to shipments when a chokepoint (Suez, Panama, Malacca) closes.
- **The four analytical use cases (each on its right store):**

| # | Analytical question | Store |
|---|---------------------|-------|
| **UC1** | Which routes/carriers/ports have the worst schedule reliability, and what drives the delays? | **BigQuery** (OLAP star) |
| **UC2** | How do congestion and dwell time at key ports trend over time? | **BigQuery** (temporal OLAP) |
| **UC3** | What share of shipments transit Suez/Panama/Malacca, and what's the impact of a closure? | **ArangoDB** (graph reachability) |
| **UC4** | What is the best alternative routing when a lane is disrupted? | **ArangoDB** (graph pathfinding) |

**Defense / speaker notes**
- The forwarder/3PL lens gives the richest cross-source story — it touches carriers, ports, lanes, and risk at once.
- The design decision that drives everything: **those four questions don't all want the same kind of database.** "Which carrier is most reliable" is an OLAP roll-up (group/average/compare); "what becomes unreachable if Suez closes" is a *network* question (paths and connections, not aggregates).

---

## Slide M3-2 — The Central Thesis: Right Store per Workload *(~1.5 min — the graded core)*

**Slide content**
- **Hybrid analytical layer:** a **BigQuery star-schema warehouse** for the OLAP questions (UC1, UC2) + an **ArangoDB property graph** for the network questions (UC3, UC4) — *the right store per workload.*
- The split is the **thesis the whole architecture proves**: the hybrid is **justified, not incidental.**
- **OLAP, not OLTP:** read-heavy analytical queries over historical movement data (averages, trends, comparisons over millions of position records) — not a live row-level booking system.
- **The bridge that makes it one architecture:** the warehouse and the graph **share the same natural keys** — UN/LOCODE (port), IMO (vessel), SCAC (carrier). A graph route like `['USNYC','USLAX','CNSHA']` is literally a list of `dim_port` keys → joins **1:1, no fuzzy matching**, back to warehouse facts.

**Defense / speaker notes**
- "Why two databases — isn't that over-engineering?" → the workloads are genuinely different shapes. Aggregation is cheap on a columnar warehouse and awkward as graph traversals; reachability and shortest-path are natural on a graph and painful as recursive SQL. And they share keys, so it's *one* architecture with a clean join-back, not two silos.
- The clean key join-back is *why* this is one coherent hybrid and not two databases that happen to describe ships.

---

## Slide M3-3 — Processing Paradigm & Schema Design *(~2 min — the graded core)*

**Slide content**
- **Star schema, not snowflake** — fact tables in the middle, flat dimension tables around them. **4 facts + 6 conformed dimensions = 10 entities** (clears the 5–6-entity bar).
  - **Facts:** `fact_voyage_leg` (port-to-port hop; transit/distance/delay), `fact_port_call` (port visit; dwell), `fact_booking`, `fact_container_event`.
  - **Dimensions:** `dim_date`, `dim_port`, `dim_vessel`, `dim_carrier`, `dim_lane`, `dim_commodity`.
- **SCD strategy:** SCD2 on `dim_vessel` / `dim_carrier` (operator/alliance change → close old row, open new); SCD1 (overwrite) on `dim_port` / `dim_lane` / `dim_commodity`; static `dim_date`.
- **Provenance flag** on every fact row — **`real | synthetic`** — so the demo honestly distinguishes grounded vs generated data.

**Defense / speaker notes**
- **Star over snowflake, engine-specific defense:** BigQuery is a **columnar MPP** engine — storage is cheap, unused columns prune for free, **joins are the expensive part** (cross-slot shuffle). Snowflaking normalizes to *save storage* — row-store/OLTP-era thinking. On BigQuery that only buys more joins, the one thing that's actually expensive. Google's own guidance pushes even flatter (nested/repeated); a flat star is the legible middle ground for grading.
- This is the **OLAP-vs-OLTP / star-vs-snowflake** decision the rubric explicitly grades.

---

## Slide M3-4 — Transformation Pipeline (Medallion) *(~2 min — walk the arrows)*

**Slide content** — left-to-right medallion flow:

```
 RAW SOURCES            BRONZE (land as-is)        SILVER (conform + derive)         GOLD (serve)
 ───────────            ─────────────────────       ──────────────────────────        ──────────────────
 AIS GeoParquet  ─────▶ immutable, partitioned ───▶ MMSI→IMO resolve,            ┌──▶ BigQuery star
 WPI / UN/LOCODE        by date, source-format       geofence into port-calls,    │    (fact_voyage_leg…)
 chokepoints                                         derive voyage-legs,          │
 LSCI/Comtrade/LPI ───▶ priors (conditioners) ─────▶ conform dims + keys,        └──▶ ArangoDB graph
 synthetic gen     ───▶ JSONL events                 attach provenance flag           (ocean_network)
```

- **Raw → Bronze:** land everything exactly as it arrives, immutable, partitioned by date. AIS bounded to **4 US ports, cargo + tankers, ~31 days ≈ 1.88M position rows** — a defensible slice, not the whole planet.
- **Bronze → Silver (the critical path — both Gold stores read from here, never from each other):** resolve **MMSI→IMO** (stable identity, tie-break + collision count); **geofence** ports and derive port-calls from *geometry, not the AIS free-text destination*; pair calls into **voyage legs** (transit/distance/delay); conform to natural keys + stamp **provenance**.
- **Silver → Gold:** **one conformed source, two sinks** — load the star into BigQuery (partitioned + clustered, idempotent) and project the *same* entities into the ArangoDB graph where keys line up 1:1. Orchestrated by an **Airflow DAG**.

**Defense / speaker notes**
- "One conformed Silver layer is the single source of truth; everything downstream is a fan-out from it." Both stores reconcile by construction because they never read from each other.
- **Built-vs-designed honesty (stated here, detailed in the Final):** the **`fact_voyage_leg` → BigQuery path is built and runs end-to-end today** via the Airflow DAG, idempotent; the graph load and the synthetic facts are **designed and queryable on paper** — next on the roadmap. *"Here's the design, and here's the slice we already proved."*

---

## Slide M3-5 — Early Tech Stack & Cost Posture *(~1 min)*

**Slide content**
- **Storage / landing:** **Google Cloud Storage** data lake — Parquet for tabular, JSONL for events.
- **Orchestration:** **Apache Airflow 3.0** DAGs. Cost call — plain Airflow on a tiny VM, **not** managed Cloud Composer (Composer can't scale to zero, ~$300+/mo); rubric requires *Airflow*, not Composer specifically. Composer-portable if needed.
- **OLAP warehouse:** **BigQuery** — star schema, native partitioned + clustered tables.
- **Graph store:** **ArangoDB 3.12** — managed cluster (Graph Analytics Engine available). **Pregel was removed in 3.12**, so graph analytics use **AQL traversals + weighted shortest-path** (fine for our scale).
- **Data generation:** **Python — Faker + NumPy**, fully seeded → byte-for-byte reproducible from a clone (committed checksum proves it).
- **Cost posture:** AIS bounded slice stays inside a **$50/mo budget** with 50/90/100% alerts.

**Defense / speaker notes**
- "What's built vs proposed?" → the `fact_voyage_leg` slice is built and runs end-to-end (AIS → Silver → BigQuery via Airflow DAG, idempotent, answering UC1/UC2 in live SQL); the graph projection and synthetic facts are designed and queryable, building them is the next phase.
- **MSDS 681 Lakehouse:** this architecture is **designed to extend** to a Data Lakehouse next term — future work, not built here.

---

## Source-file map (where each slide's detail lives)

| Slide | Source file |
|-------|-------------|
| M3-1 | `m1-team-domain.md`, `m1-use-cases.md`, `m3-pitch-talking-points.md` Slide 1 |
| M3-2 | `m3-pitch-talking-points.md` Slide 2e, `m2-conformed-keys.md` |
| M3-3 | `m2-bq-star.md`, `m2-star-vs-snowflake.md` |
| M3-4 | `m3-pitch-talking-points.md` Slide 3 |
| M3-5 | `m3-pitch-talking-points.md` Slide 4, `CLAUDE.md` |
