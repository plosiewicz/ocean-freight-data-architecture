# Final Deck Source — Final Presentation & Demo (DEL-04)

> **Manual step:** This file is the repo-side source of truth. Placing this content onto the Final "Presentation & Demo" section of the shared Google Slides deck is a manual copy-paste step — do not create a new deck.
>
> **Purpose:** A ~10-min Final-presentation brief — architecture overview, the hybrid-justification argument, the **four use-case results** (with the frozen citable numbers), and the **honest built-vs-designed framing** — backed by the working demo (`docs/demo.ipynb`) and its recorded backup. Each section below maps to **one slide**. Copy the **Slide content** into the shared Google Slides deck; the **Defense / speaker notes** are what you say out loud or keep for Q&A.
>
> **Do not create a new deck** — all milestones live in the single shared deck (rubric rule).
>
> **Numbers note:** the UC3/UC4 result figures below are transcribed from the committed
> `data/golden/uc3.golden.json` / `data/golden/uc4.golden.json` (read at authoring time,
> frozen 2026-06-16), not remembered literals — they reproduce the live gate-19 non-degeneracy proof.

---

## What the Final is grading (keep this in mind)

- **Final (~10 min + Q&A):** present the **complete architecture**, defend the **hybrid** design, demonstrate a **working demo answering all four use cases**, and present the designed-but-not-built remainder **honestly**.
- The demo surface is a Jupyter notebook (`docs/demo.ipynb`) reading **frozen snapshots** so it cannot fail live; a recorded backup is the can't-fail fallback.
- This architecture is **designed to extend** to the MSDS 681 Data Lakehouse next term (future work, not built here).

---

# FINAL — Presentation & Demo (6 slides, ~10 min)

## Slide F-1 — Recap: Team, Domain & the Hybrid Thesis *(~1 min)*

**Slide content**
- **Team:** Grilled Cheesin — P.J. Losiewicz · Borna Karimi · Alexander Mohun
- **Domain:** end-to-end data architecture for an **ocean freight forwarder / 3PL**.
- **Thesis:** a **hybrid analytical layer** — a **BigQuery star-schema warehouse** for OLAP questions (UC1, UC2) + an **ArangoDB property graph** for network questions (UC3, UC4) — answering each on the **right store per workload**. The hybrid is **justified, not incidental.**

**Defense / speaker notes**
- One-line reframe of the whole project: the four questions don't all want the same database — aggregation roll-ups go to the columnar warehouse, reachability/pathfinding go to the graph, and shared natural keys make it *one* architecture.

---

## Slide F-2 — The Architecture End-to-End *(~2 min)*

**Slide content** — the full Bronze → Silver → hybrid-Gold pipeline, **one transform, two sinks**, orchestrated by Airflow:

```
 RAW SOURCES            BRONZE (land as-is)        SILVER (conform + derive)         GOLD (serve)
 ───────────            ─────────────────────       ──────────────────────────        ──────────────────
 AIS GeoParquet  ─────▶ immutable, partitioned ───▶ MMSI→IMO resolve,            ┌──▶ BigQuery star
 WPI / UN/LOCODE        by date, source-format       geofence into port-calls,    │    (fact_voyage_leg…)
 chokepoints                                         derive voyage-legs,          │
 LSCI/Comtrade/LPI ───▶ priors (conditioners) ─────▶ conform dims + keys,        └──▶ ArangoDB graph
 synthetic gen     ───▶ JSONL events                 attach provenance flag           (ocean_network)
```

- **Bronze:** immutable, date-partitioned landing of real AIS (≈1.88M position rows, 4 US ports / cargo+tankers / ~31 days), port reference, chokepoints, trade-flow priors, and synthetic events.
- **Silver (critical path):** MMSI→IMO identity resolution; geofence-derived port-calls (from geometry, not AIS destination text); voyage-leg derivation; conform to natural keys + provenance flag. **Both Gold stores read from Silver, never from each other.**
- **Gold:** **one conformed source, two sinks** — the BigQuery star (partitioned + clustered, idempotent) and the ArangoDB `ocean_network` graph, sharing UN/LOCODE / IMO / SCAC keys 1:1.
- **Orchestration:** an **Airflow 3.0 DAG** runs the load legs (`load_bq` ∥ `load_arango`) plus a cross-store reconcile/verify step.

**Defense / speaker notes**
- "How do you keep the two stores consistent?" → they never read from each other; both read the **same conformed Silver layer**, so a shared-key metric (e.g. "shipments transiting Suez") reconciles between stores by construction. That's the cross-store consistency gate.

---

## Slide F-3 — UC1 & UC2 on the BigQuery Star (OLAP) *(~1.5 min)*

**Slide content**
- **UC1 — ETA reliability** *(BigQuery)*: on-time % and average schedule delta by carrier / lane / port, surfacing the worst performers. Carrier attributed via `operated_by → dim_carrier`. Live SQL over `fact_voyage_leg` (`sql/uc1_eta_reliability.sql`).
- **UC2 — Port congestion / dwell trend** *(BigQuery)*: per-port turnaround (dwell) rolled up and trended across the ~31-date slice (`sql/uc2_dwell_trend.sql`).
- Both are classic columnar roll-ups — group, average, compare, trend — exactly what the star schema and partition pruning are tuned for.

**Defense / speaker notes**
- These are the OLAP questions: read-heavy aggregations over historical movement data. Partition pruning on the date surrogate is the biggest cost lever; clustering on the high-selectivity FKs keeps the scans cheap.
- Demoed as **versioned SQL on disk** (`sql/uc*.sql`) with rendered results in the notebook — parallel to the graph half's versioned AQL.

---

## Slide F-4 — UC3 & UC4 on the ArangoDB Graph (Network) — the citable results *(~2.5 min — the demo centerpiece)*

**Slide content**

**UC3 — Chokepoint exposure & closure impact** *(ArangoDB)*
- **Transit share** (share of the 40-lane network transiting each chokepoint):

  | Chokepoint | Transiting lanes | Transit share |
  |------------|------------------|---------------|
  | **PANAMA** | 20 / 40 | **50.0%** |
  | **GIBRALTAR** | 16 / 40 | **40.0%** |
  | **SUEZ** | 12 / 40 | **30.0%** |
  | **MALACCA** | 0 / 40 | **0.0%** (documented zero) |

- **SUEZ closure → reroute impact:** USNYC → CNSHA baseline **355.97 h**; with SUEZ-transiting lanes disabled the best reroute is **432.19 h** → **delta +76.22 h**. (Closure is reversible — disable the SUEZ-transiting lanes, re-run weighted shortest-path; no data dropped.)
- **GIBRALTAR closure → genuine unreachability:** reachable ports across origins drop from **29 (open) → 11 (closed)** — the closure genuinely disconnects part of the network, not just adds cost.

**UC4 — Disruption rerouting** *(ArangoDB)*
- Baseline path **USNYC → CNSHA** (355.97 h); under the same lane disruption the weighted shortest-path reroutes **USNYC → USLAX → CNSHA** (118.4 h + 313.79 h = 432.19 h) → **delta +76.22 h**. The path genuinely differs (detours via USLAX) — proving the reroute logic is non-degenerate.

**Defense / speaker notes**
- "Why not do this in SQL?" → UC3/UC4 are "what's reachable if a node disappears" and "shortest weighted path under disruption" — natural on a graph engine (named-graph traversal + `K_SHORTEST_PATHS`), painful and unreadable as recursive SQL CTEs.
- These exact numbers come from the frozen goldens (`data/golden/uc3.golden.json`, `uc4.golden.json`) and reproduce the **live gate-19 anti-degeneracy proof** — the notebook asserts *direction* (reroute delta > 0, closed-reachable < open-reachable) so it can never silently render a degenerate (all-zero) result. **No Pregel** — removed in 3.12; this is pure AQL traversal + weighted shortest-path.

---

## Slide F-5 — Built vs Designed: the Honest Frame *(~1.5 min — required honesty slide)*

**Slide content**
- **BUILT — one fully-implemented ETL slice:** **AIS → `fact_voyage_leg`**, Bronze → Silver → BigQuery, **orchestrated by the Airflow DAG**, **idempotent** (re-runs leave row counts unchanged), and **cross-store-gated** (BigQuery ↔ ArangoDB reconcile). It answers UC1/UC2 in live SQL and feeds the graph that answers UC3/UC4.
- **DESIGNED & QUERYABLE (not built):** the other three facts (`fact_port_call`, `fact_booking`, `fact_container_event`), the full SCD2 dimension history, and the synthetic-event volume — designed in the ER/star/graph models and queryable on paper, implemented later.
- **Every fact row carries a `provenance` flag (`real | synthetic`)** — the architecture states what is grounded vs generated at the row level.
- **"Here's the design, and here's the slice we already proved."**

**Defense / speaker notes**
- This is the academic-integrity frame the brief invites: we do **not** overstate scope. One vertical slice is genuinely implemented end-to-end; the remainder is honestly marked designed-and-queryable.
- "How much is real vs made up?" → ship movements / ports / codes are **real**; LSCI / Comtrade / LPI are **real but used only as conditioners** (priors, never facts); bookings / container events are **synthetic** (a forwarder's book is private) but conditioned on the real indices and flagged.

---

## Slide F-6 — The Working Demo & What's Next *(~1.5 min)*

**Slide content**
- **Demo surface:** `docs/demo.ipynb` — a four-UC Jupyter notebook (UC1/UC2 from the BigQuery star, UC3/UC4 from the ArangoDB graph). It reads the **committed frozen `data/golden/uc*.golden.json` snapshots by default**, so it runs top-to-bottom **from a fresh clone with no credentials** and **cannot fail live**.
- **Failure-proofing:** a `gate_demo_notebook` ship-gate re-executes the notebook credential-free and asserts a clean exit; a **recorded backup** of the run is the can't-fail-live fallback (see `docs/07-RECORD-BACKUP.md`). An optional `LIVE = True` aside hits BQ / the Arango cluster directly — *"look, it's real"* — never required to render.
- **No graph Web UI visualizer** — the graph half is demoed via the back-end DB + native algorithms (AQL traversal / `K_SHORTEST_PATHS`), returned programmatically, parallel to the OLAP half's versioned SQL.
- **What's next:** build the remaining three facts + SCD2 history; the architecture is **designed to extend** to the MSDS 681 **Data Lakehouse** next term.

**Defense / speaker notes**
- The demo is deliberately failure-proof: the default path touches no network and no secrets, so a flaky conference Wi-Fi or an expired token can't break the presentation. The recorded backup is the belt-and-suspenders.
- **MSDS 681 Lakehouse** is named only as **designed to extend** — future work, not built in this course.

---

## Source-file map (where each slide's detail lives)

| Slide | Source file |
|-------|-------------|
| F-1 | `m1-team-domain.md`, `m3-pitch-talking-points.md` Slide 1 |
| F-2 | `m3-pitch-talking-points.md` Slide 3, `m2-conformed-keys.md` |
| F-3 | `sql/uc1_eta_reliability.sql`, `sql/uc2_dwell_trend.sql`, `m2-bq-star.md` |
| F-4 | `data/golden/uc3.golden.json`, `data/golden/uc4.golden.json`, `06-VERIFICATION.md`, `aql/uc*.aql` |
| F-5 | `m3-pitch-talking-points.md` intro + Slide 2c, `m2-gap-analysis.md` |
| F-6 | `docs/demo.ipynb`, `docs/07-RECORD-BACKUP.md`, `CLAUDE.md` |
