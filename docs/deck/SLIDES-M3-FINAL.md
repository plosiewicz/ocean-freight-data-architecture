# M3 + Final Slide Context — Grilled Cheesin

> **Manual step:** This file is the repo-side source of truth (the assembled M3 + Final brief).
> Placing this content onto the M3 / Final slides in the shared Google Slides deck is a manual
> copy-paste step — do not create a new deck.
>
> **Purpose:** One consolidated, slide-ready brief for the **M3 Midterm Design Pitch (~7 min)**
> and the **Final Presentation & Demo (~10 min)**, assembled from `docs/deck/m3-pitch.md`,
> `docs/deck/final-presentation.md`, `docs/team-materials/m3-pitch-talking-points.md`, and the
> frozen UC results in `data/golden/`. Each section below maps to **one slide**. Copy the
> **Slide content** into the shared Google Slides deck; the **Defense / speaker notes** are what
> you say out loud or keep for Q&A.
>
> **Do not create a new deck** — all milestones live in the single shared deck (rubric rule).
>
> **Numbers note:** the UC3/UC4 figures are transcribed from the committed
> `data/golden/uc3.golden.json` / `uc4.golden.json` (frozen 2026-06-16) — they reproduce the live
> gate-19 non-degeneracy proof, not remembered literals.

---

## What the rubric is grading (keep this in mind per slide)

- **M3 — Midterm Design Pitch (~7 min):** present and **defend** the design — domain, analytical
  questions, OLAP-vs-OLTP, star-vs-snowflake, the transformation pipeline, the tech stack. The
  brief says you needn't have built it yet; we present *"here's the design, and here's the slice we
  already proved."*
- **Final (~10 min):** the complete architecture + hybrid justification + a **working demo answering
  all four use cases** + an **honest built-vs-designed** account.
- Graders reward **defending** choices, not just stating them.
- This design seeds the **MSDS 681 Lakehouse** next term — the architecture is **designed to extend**
  (not built here).

---

# MILESTONE 3 — Midterm Design Pitch (5 slides, ~7 min)

## Slide M3-1 — Team, Domain & Business Goal *(~1 min)*

**Slide content**
- **Team:** Grilled Cheesin — P.J. Losiewicz · Borna Karimi · Alexander Mohun
- **Domain:** end-to-end data architecture for a **freight forwarder / 3PL** in **global ocean
  container logistics** — a middleman that books cargo on ships it doesn't own.
- **Business goal:** **risk & reliability** — unreliable routes/carriers, port congestion, and
  closure impact at chokepoints (Suez, Panama, Malacca).
- **Four use cases (each on its right store):**

| # | Analytical question | Store |
|---|---------------------|-------|
| **UC1** | Worst schedule reliability by route/carrier/port, and what drives the delays? | **BigQuery** (OLAP star) |
| **UC2** | How do congestion and dwell time at key ports trend over time? | **BigQuery** (temporal OLAP) |
| **UC3** | Share of shipments transiting Suez/Panama/Malacca, and the impact of a closure? | **ArangoDB** (graph reachability) |
| **UC4** | Best alternative routing when a lane is disrupted? | **ArangoDB** (graph pathfinding) |

**Defense / speaker notes**
- Those four questions don't all want the same database — aggregation roll-ups (UC1/UC2) vs network
  reachability/pathfinding (UC3/UC4).

---

## Slide M3-2 — The Central Thesis: Right Store per Workload *(~1.5 min — graded core)*

**Slide content**
- **Hybrid analytical layer:** BigQuery star (OLAP: UC1/UC2) + ArangoDB graph (network: UC3/UC4) —
  the **right store per workload**; the hybrid is **justified, not incidental.**
- **OLAP, not OLTP:** read-heavy analytics over historical movement data, not a live booking system.
- **The bridge:** warehouse and graph **share natural keys** — UN/LOCODE, IMO, SCAC. A graph route
  `['USNYC','USLAX','CNSHA']` is a list of `dim_port` keys → joins **1:1** back to facts.

**Defense / speaker notes**
- "Why two databases?" → genuinely different workload shapes; shared keys make it *one* architecture
  with a clean join-back, not two silos.

---

## Slide M3-3 — Processing Paradigm & Schema Design *(~2 min — graded core)*

**Slide content**
- **Star schema, not snowflake** — **4 facts + 6 dimensions = 10 entities.**
  - **Facts:** `fact_voyage_leg`, `fact_port_call`, `fact_booking`, `fact_container_event`.
  - **Dimensions:** `dim_date`, `dim_port`, `dim_vessel`, `dim_carrier`, `dim_lane`, `dim_commodity`.
- **SCD:** SCD2 on `dim_vessel`/`dim_carrier`; SCD1 (overwrite) on `dim_port`/`dim_lane`/`dim_commodity`; static `dim_date`.
- **Provenance flag** (`real | synthetic`) on every fact row.

**Defense / speaker notes**
- **Star over snowflake:** BigQuery is columnar MPP — storage cheap, columns prune free, **joins are
  the expensive part**. Snowflaking saves storage (OLTP-era thinking) at the cost of more joins — the
  one expensive thing here. Flat star is the legible middle ground.

---

## Slide M3-4 — Transformation Pipeline (Medallion) *(~2 min)*

**Slide content**

```
 RAW SOURCES            BRONZE (land as-is)        SILVER (conform + derive)         GOLD (serve)
 ───────────            ─────────────────────       ──────────────────────────        ──────────────────
 AIS GeoParquet  ─────▶ immutable, partitioned ───▶ MMSI→IMO resolve,            ┌──▶ BigQuery star
 WPI / UN/LOCODE        by date, source-format       geofence into port-calls,    │    (fact_voyage_leg…)
 chokepoints                                         derive voyage-legs,          │
 LSCI/Comtrade/LPI ───▶ priors (conditioners) ─────▶ conform dims + keys,        └──▶ ArangoDB graph
 synthetic gen     ───▶ JSONL events                 attach provenance flag           (ocean_network)
```

- **Bronze:** immutable, date-partitioned; AIS bounded to ~1.88M rows (4 US ports / cargo+tankers / ~31 days).
- **Silver (critical path):** MMSI→IMO; geofence-derived port-calls (geometry, not destination text); voyage legs; conform + provenance. **Both Gold stores read from Silver, never from each other.**
- **Gold:** one conformed source, two sinks (BigQuery star ∥ ArangoDB graph), shared keys 1:1; orchestrated by an **Airflow DAG**.

**Defense / speaker notes**
- "One conformed Silver layer is the single source of truth; everything downstream is a fan-out."
- **Built-vs-designed:** the `fact_voyage_leg` → BigQuery path is built and runs end-to-end today; the
  graph load and synthetic facts are designed and queryable — next on the roadmap.

---

## Slide M3-5 — Early Tech Stack & Cost Posture *(~1 min)*

**Slide content**
- **GCS** landing (Parquet + JSONL) · **Airflow 3.0** DAGs (plain Airflow on a tiny VM, not managed
  Composer — cost call) · **BigQuery** star (partitioned + clustered) · **ArangoDB 3.12** managed
  cluster (**Pregel removed → AQL traversals + weighted shortest-path**) · **Python Faker + NumPy**
  seeded (byte-reproducible, committed checksum) · **$50/mo** budget with 50/90/100% alerts.

**Defense / speaker notes**
- "What's built vs proposed?" → the `fact_voyage_leg` slice is built end-to-end (AIS → Silver →
  BigQuery via Airflow DAG, idempotent, UC1/UC2 in live SQL); graph projection + synthetic facts are
  designed-and-queryable, next phase.
- **MSDS 681 Lakehouse:** **designed to extend** — future work, not built here.

---

# FINAL — Presentation & Demo (6 slides, ~10 min)

## Slide F-1 — Recap: Team, Domain & the Hybrid Thesis *(~1 min)*

**Slide content**
- **Team Grilled Cheesin** — P.J. Losiewicz · Borna Karimi · Alexander Mohun · **Domain:** ocean
  freight forwarder / 3PL.
- **Thesis:** hybrid analytical layer — BigQuery star (OLAP: UC1/UC2) + ArangoDB graph (network:
  UC3/UC4) — **right store per workload**; the hybrid is **justified, not incidental.**

**Defense / speaker notes**
- The four questions don't all want the same database; shared natural keys make it *one* architecture.

---

## Slide F-2 — The Architecture End-to-End *(~2 min)*

**Slide content** — full Bronze → Silver → hybrid-Gold pipeline, **one transform, two sinks**, Airflow-orchestrated:

```
 RAW SOURCES            BRONZE (land as-is)        SILVER (conform + derive)         GOLD (serve)
 ───────────            ─────────────────────       ──────────────────────────        ──────────────────
 AIS GeoParquet  ─────▶ immutable, partitioned ───▶ MMSI→IMO resolve,            ┌──▶ BigQuery star
 WPI / UN/LOCODE        by date, source-format       geofence into port-calls,    │    (fact_voyage_leg…)
 chokepoints                                         derive voyage-legs,          │
 LSCI/Comtrade/LPI ───▶ priors (conditioners) ─────▶ conform dims + keys,        └──▶ ArangoDB graph
 synthetic gen     ───▶ JSONL events                 attach provenance flag           (ocean_network)
```

- **Bronze** immutable date-partitioned landing (≈1.88M AIS rows + reference + priors + synthetic).
- **Silver (critical path):** MMSI→IMO; geofence port-calls; voyage legs; conform + provenance. **Both Gold stores read from Silver, never from each other.**
- **Gold:** BigQuery star (partitioned + clustered, idempotent) ∥ ArangoDB `ocean_network`, shared UN/LOCODE / IMO / SCAC keys 1:1.
- **Airflow 3.0 DAG** runs `load_bq` ∥ `load_arango` + a cross-store reconcile/verify step.

**Defense / speaker notes**
- "How do you keep the stores consistent?" → both read the same Silver, so shared-key metrics
  reconcile by construction — the cross-store gate.

---

## Slide F-3 — UC1 & UC2 on the BigQuery Star (OLAP) *(~1.5 min)*

**Slide content**
- **UC1 — ETA reliability** *(BigQuery)*: on-time % + avg schedule delta by carrier/lane/port,
  worst-first; carrier via `operated_by → dim_carrier` (`sql/uc1_eta_reliability.sql`).
- **UC2 — Port congestion / dwell trend** *(BigQuery)*: per-port turnaround trended across the
  ~31-date slice (`sql/uc2_dwell_trend.sql`).
- Classic columnar roll-ups — group, average, compare, trend.

**Defense / speaker notes**
- OLAP questions: partition pruning on the date surrogate is the biggest cost lever; clustering on
  high-selectivity FKs keeps scans cheap. Demoed as versioned SQL on disk + rendered notebook output.

---

## Slide F-4 — UC3 & UC4 on the ArangoDB Graph (Network) — citable results *(~2.5 min — demo centerpiece)*

**Slide content**

**UC3 — Chokepoint exposure & closure impact** *(ArangoDB)*
- **Transit share** (of the 40-lane network):

  | Chokepoint | Transiting lanes | Transit share |
  |------------|------------------|---------------|
  | **PANAMA** | 20 / 40 | **50.0%** |
  | **GIBRALTAR** | 16 / 40 | **40.0%** |
  | **SUEZ** | 12 / 40 | **30.0%** |
  | **MALACCA** | 0 / 40 | **0.0%** (documented zero) |

- **SUEZ closure → reroute impact:** USNYC → CNSHA baseline **355.97 h**; SUEZ-lanes disabled → best
  reroute **432.19 h** → **delta +76.22 h** (reversible closure, no data dropped).
- **GIBRALTAR closure → genuine unreachability:** reachable ports **29 (open) → 11 (closed)** — the
  closure genuinely disconnects part of the network.

**UC4 — Disruption rerouting** *(ArangoDB)*
- Baseline **USNYC → CNSHA** (355.97 h); under disruption the weighted shortest-path reroutes
  **USNYC → USLAX → CNSHA** (118.4 h + 313.79 h = 432.19 h) → **delta +76.22 h** (path genuinely
  detours via USLAX).

**Defense / speaker notes**
- "Why not in SQL?" → "what's reachable if a node disappears" + "shortest weighted path under
  disruption" are natural on a graph (named-graph traversal + `K_SHORTEST_PATHS`), painful as
  recursive SQL. Numbers come from the frozen goldens and reproduce the live **gate-19** anti-degeneracy
  proof — the notebook asserts *direction* (delta > 0, closed-reachable < open-reachable). **No Pregel**
  (removed in 3.12).

---

## Slide F-5 — Built vs Designed: the Honest Frame *(~1.5 min — required honesty slide)*

**Slide content**
- **BUILT — one fully-implemented ETL slice:** **AIS → `fact_voyage_leg`**, Bronze → Silver →
  BigQuery, **Airflow-orchestrated**, **idempotent**, **cross-store-gated**. Answers UC1/UC2 in live
  SQL and feeds the graph behind UC3/UC4.
- **DESIGNED & QUERYABLE (not built):** `fact_port_call`, `fact_booking`, `fact_container_event`,
  full SCD2 history, the synthetic-event volume — designed in the models, implemented later.
- **`provenance` flag (`real | synthetic`)** on every fact row.
- **"Here's the design, and here's the slice we already proved."**

**Defense / speaker notes**
- The academic-integrity frame: we don't overstate scope. "Real vs made up?" → ships/ports/codes
  **real**; LSCI/Comtrade/LPI **real but priors only**; bookings/container events **synthetic** but
  conditioned and flagged.

---

## Slide F-6 — The Working Demo & What's Next *(~1.5 min)*

**Slide content**
- **Demo surface:** `docs/demo.ipynb` — four-UC notebook (UC1/UC2 BigQuery, UC3/UC4 ArangoDB) reading
  the committed frozen `data/golden/uc*.golden.json` snapshots by default → runs **from a fresh clone
  with no credentials**, **cannot fail live**.
- **Failure-proofing:** `gate_demo_notebook` re-executes credential-free + asserts clean exit; a
  **recorded backup** is the fallback (`docs/07-RECORD-BACKUP.md`); an optional `LIVE = True` aside hits
  BQ / the cluster (*"look, it's real"*), never required.
- **No graph Web UI visualizer** — back-end DB + native algorithms (AQL / `K_SHORTEST_PATHS`),
  returned programmatically.
- **What's next:** build the remaining facts + SCD2 history; architecture is **designed to extend** to
  the MSDS 681 **Data Lakehouse** next term.

**Defense / speaker notes**
- The default demo path touches no network/secrets, so flaky Wi-Fi or an expired token can't break the
  presentation; the recorded backup is belt-and-suspenders. **MSDS 681 Lakehouse** is named only as
  **designed to extend** — future work.

---

## Source-file map (where each slide's detail lives)

| Slide | Source file |
|-------|-------------|
| M3-1..M3-5 | `m3-pitch.md`, `m3-pitch-talking-points.md`, `m1-team-domain.md`, `m2-bq-star.md`, `m2-star-vs-snowflake.md` |
| F-1, F-2 | `final-presentation.md`, `m2-conformed-keys.md` |
| F-3 | `sql/uc1_eta_reliability.sql`, `sql/uc2_dwell_trend.sql` |
| F-4 | `data/golden/uc3.golden.json`, `data/golden/uc4.golden.json`, `06-VERIFICATION.md` |
| F-5 | `m2-gap-analysis.md`, `m3-pitch-talking-points.md` |
| F-6 | `docs/demo.ipynb`, `docs/07-RECORD-BACKUP.md`, `CLAUDE.md` |
