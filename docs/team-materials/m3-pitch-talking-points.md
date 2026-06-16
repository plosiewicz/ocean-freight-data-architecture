# M3 Midterm Design Pitch — Slide Outline & Talking Points

> **Team Grilled Cheesin · ~7 min + Q&A.** Spoken-word talking points, written to be *said out loud* — not read off the slide. Jargon is fine for a data-architecture master's audience; the **domain** (freight/shipping) terms are spelled out so nobody on the team trips over them. Timing budget in each header.
>
> **One thing to lean on:** the brief says "you don't need to have built this yet." We have. The voyage-leg slice runs end-to-end into BigQuery today. So we present as *"here's the design, and here's the slice we already proved."*

---

## Domain cheat-sheet (read once before presenting — don't say these wrong)

- **Freight forwarder / 3PL** — a logistics middleman. They don't own the ships; they book cargo space on other people's vessels and manage the shipment end to end for their customers. Our whole architecture is built from *their* point of view.
- **AIS** — Automatic Identification System. Every large ship broadcasts its position, speed, and ID on a radio signal, like a transponder on a plane. It's public. This is our real ground-truth movement data.
- **MMSI vs IMO** — two ship IDs. **MMSI** is on every AIS ping (reliable for *joining*) but can change when a ship re-registers. **IMO** is a permanent 7-digit hull ID that never changes — so IMO is our real identity key, MMSI is just how we *find* the ship in the feed.
- **Port call** — a ship arriving at a port, sitting there, and leaving. **Dwell / turnaround** = how long it sat.
- **Voyage leg** — one port-to-port hop: depart A, arrive B.
- **Lane** — a trade route between two ports (e.g. Shanghai → LA).
- **Chokepoint** — a narrow passage almost all global shipping squeezes through: Suez Canal, Panama Canal, Strait of Malacca.
- **Proforma schedule** — the *planned* timetable a carrier publishes. "Schedule delta" = actual minus planned = how late the ship was.
- **UN/LOCODE, SCAC, HS code** — standard codes for a port, a carrier, and a commodity type, respectively. They're our "natural keys."

---

## Slide 1 — Domain & Business Goal *(~1 min)*

**Talking points (say it like this):**

- "We're **Grilled Cheesin** — P.J., Borna, and Alex. Our domain is an **ocean freight forwarder** — think of a logistics company that books container cargo on ships it doesn't own, across global trade lanes."
- "The business problem we're solving for them is **risk and reliability**: which routes and carriers are unreliable, where are ports getting congested, and what happens to my shipments if a major chokepoint like Suez shuts down."
- "Here's the design decision that drives everything: **those questions don't all want the same kind of database.** 'Which carrier is most reliable' is a classic OLAP roll-up — group, average, compare. But 'what becomes unreachable if Suez closes' is a *network* question — it's about paths and connections, not aggregates."
- "So our core thesis is a **hybrid analytical layer: a BigQuery star schema for the OLAP questions, and an ArangoDB property graph for the network questions** — the right store per workload. The point of the pitch is to show that the hybrid is *justified*, not just us using two cool tools."

**The four use cases (put on the slide, say briefly):**
- **UC1 — ETA reliability:** which routes/carriers/ports have the worst on-time performance, and why. *(BigQuery)*
- **UC2 — Port congestion / dwell trends:** how dwell time at key ports trends over time. *(BigQuery)*
- **UC3 — Chokepoint exposure:** what share of shipments transit Suez/Panama/Malacca, and the impact of a closure. *(ArangoDB)*
- **UC4 — Rerouting:** best alternative route when a lane is disrupted. *(ArangoDB)*

---

## Slide 2 — Processing Paradigm & Schema Design *(~2 min — this is the graded core)*

### 2a. OLAP, not OLTP

- "First question the rubric asks: OLAP or OLTP? We're **OLAP** — analytical. We're not running a live booking system that needs row-level inserts and updates all day; we're running **read-heavy analytical queries over historical movement data** — averages, trends, comparisons across millions of position records. That's OLAP, and it's what points us at a columnar warehouse like BigQuery."

### 2b. Star, not snowflake — and *why*

- "Schema: we chose a **star schema** — fact tables in the middle, flat dimension tables around them — over a normalized **snowflake**."
- "Here's the defense, and it's specific to the engine. **BigQuery is a columnar MPP engine.** Storage is cheap, and it only scans the columns your query actually touches — unused columns are free. But **joins are expensive** — they make the system shuffle data across nodes."
- "Snowflaking normalizes dimensions to *save storage*. That's **row-store, OLTP-era thinking** — it made sense when storage was the bottleneck. On BigQuery, storage isn't the bottleneck, so all snowflaking buys you is *more joins* — which is the one thing that's actually expensive here. So we keep dimensions **flat**. Google's own guidance actually pushes even further than us toward denormalization; a flat star is the legible middle ground."

### 2c. The model — facts and dimensions

- "Our model is **4 fact tables and 6 conformed dimensions.**"
- **Facts** (the measurable events): `fact_voyage_leg` (one port-to-port hop, with transit time and delay), `fact_port_call` (one port visit, with dwell time), `fact_booking`, and `fact_container_event`."
- **Dimensions** (the context you slice by): `dim_date`, `dim_port`, `dim_vessel`, `dim_carrier`, `dim_lane`, `dim_commodity`."
- "Two honesty notes we'll call out on the slide: **only `fact_voyage_leg` is actually built** right now — the other three are *designed now, implemented later*. And every fact row carries a **`provenance` flag — real or synthetic** — so we can always show what's grounded in real data versus generated."

### 2d. SCD strategy (mention briefly — it's a dimensional-modeling flex)

- "We track history where it matters. **`dim_vessel` and `dim_carrier` are SCD Type 2** — if a ship changes operator or flag, or a carrier changes shipping alliance, we close the old row and open a new one, so historical facts still point at who-it-was-then. The reference dimensions — port, lane, commodity — are **SCD Type 1**, just overwrite, because there's no analytical value in their history."

### 2e. The hybrid bridge (the killer point)

- "Last thing, and it's the one that makes the hybrid defensible: **the warehouse and the graph share the same natural keys** — UN/LOCODE for ports, IMO for vessels, SCAC for carriers."
- "So when the graph hands back a route like `['USHOU','PACTB','CNSHA']`, that's literally a list of `dim_port` keys — it joins **1:1, no fuzzy matching**, straight back to warehouse facts. That clean join-back is *why* this is one coherent architecture and not two databases that happen to describe ships."

---

## Slide 3 — Transformation Pipeline *(2–3 min — show the diagram, walk the arrows)*

> Put a left-to-right **medallion diagram** on the slide. Walk it stage by stage. Say "we've actually run this for the voyage-leg path" at the end.

**The flow to draw:**

```
 RAW SOURCES            BRONZE (land as-is)        SILVER (conform + derive)         GOLD (serve)
 ───────────            ─────────────────────       ──────────────────────────        ──────────────────
 AIS GeoParquet  ─────▶ immutable, partitioned ───▶ MMSI→IMO resolve,            ┌──▶ BigQuery star
 WPI / UN/LOCODE        by date, source-format       geofence into port-calls,    │    (fact_voyage_leg…)
 chokepoints                                         derive voyage-legs,          │
 LSCI/Comtrade/LPI ───▶ priors (conditioners) ─────▶ conform dims + keys,        └──▶ ArangoDB graph
 synthetic gen     ───▶ JSONL events                 attach provenance flag           (ocean_network)
```

**Walk it like this (label each step with what the transform DOES):**

1. **"Raw → Bronze: land everything exactly as it arrives, and never touch it again."** Real AIS ship tracks as Parquet, port reference, chokepoint nodes, the trade-flow priors, and our synthetic events. Bronze is immutable and partitioned by date. We bound the AIS to **4 US ports, cargo + tankers, ~31 days — about 1.88 million position rows** — so it's a defensible slice, not the whole planet.
2. **"Bronze → Silver: this is where the real work happens, and it's the critical path — both Gold stores read from here, never from each other."** Three transforms to call out:
   - **Resolve identity:** collapse the noisy **MMSI** pings to a stable **IMO** per ship, with a documented tie-break and a reported collision count.
   - **Derive events from geometry, not text:** we draw **geofences** — circles — around each port, and detect a port call when a ship enters, dwells, and exits. We deliberately do *not* trust the AIS free-text "destination" field. Then we pair consecutive calls into **voyage legs** and compute transit time, distance, and delay-vs-schedule.
   - **Conform + tag:** standardize every entity to its natural key (UN/LOCODE, IMO, SCAC), assign surrogate keys, and stamp the **real/synthetic provenance** flag.
3. **"Silver → Gold: fan out to two stores from one conformed source."** Load the star into BigQuery (partitioned + clustered native tables, idempotent), and project the *same* entities into the ArangoDB graph where the keys line up 1:1.
4. **"And the honest part:"** the **voyage-leg → BigQuery path is built and runs end-to-end today**, orchestrated by an Airflow DAG; re-running it leaves row counts unchanged. The graph load and the synthetic facts are designed and next on the roadmap.

**Concrete example to mention** (the brief loves a worked example): "clean and resolve MMSI→IMO → geofence positions into port-calls → pair calls into voyage-legs and compute delay → load into `fact_voyage_leg`." That's our version of their `fact_daily_sales` walkthrough.

---

## Slide 4 — Early Tech Stack *(~1 min — list or simple diagram)*

**Say it fast, grouped by layer:**

- **Storage / landing:** **Google Cloud Storage** — the data lake. Parquet for tabular, JSONL for events.
- **Orchestration:** **Apache Airflow 3.0** DAGs. Deliberate cost call — we run **plain Airflow on a tiny VM, not managed Cloud Composer**, because Composer can't scale to zero and runs ~$300+/mo; the rubric requires *Airflow*, not Composer specifically. Composer-portable if we ever need it.
- **OLAP warehouse:** **BigQuery** — the star schema, native partitioned + clustered tables.
- **Graph store:** **ArangoDB 3.12 Community Edition**, single node. One note we'll own: **Pregel was removed in 3.12**, so our graph analytics use **AQL traversals and weighted shortest-path**, not Pregel — which is actually fine for our scale.
- **Data generation:** **Python — Faker + NumPy**, fully seeded, so synthetic data is byte-for-byte reproducible from a clone (we have a committed checksum proving it).
- **The unifying idea:** "one conformed Silver layer is the single source of truth; everything downstream is a fan-out from it."

---

## Q&A Prep — anticipated questions + crisp answers

> The brief guarantees ≥2 questions (instructor + peer). These are the ones a data-arch class will actually ask. Keep answers to ~20 seconds.

- **"Why two databases? Isn't that over-engineering?"**
  → "Because the workloads are genuinely different shapes. Aggregation questions are cheap on a columnar warehouse and awkward as graph traversals; reachability and shortest-path are natural on a graph and painful as recursive SQL joins. And critically — they share natural keys, so it's *one* architecture with a clean join-back, not two silos."

- **"Why star and not snowflake — isn't normalization best practice?"**
  → "Normalization is best practice on *row-store OLTP* systems where storage and write-anomalies matter. BigQuery is columnar — storage is cheap, unused columns are free, joins are the expensive part. Snowflaking would only add join cost to save storage we don't need to save."

- **"How much of this is real vs. made up?"**
  → "Ship movements, ports, and codes are **real** public data. Trade indices — LSCI, Comtrade, LPI — are **real but used only as conditioners**, never stored as facts. Bookings and container events are **synthetic**, because a forwarder's internal book is private — but we *condition* the synthetic data on the real indices so it's plausible, and every row is flagged real or synthetic."

- **"Why not just put everything in BigQuery and do graph stuff in SQL?"**
  → "You can fake a few hops with recursive CTEs, but UC3/UC4 are 'what's reachable if a node disappears' and 'shortest weighted path under disruption' — that's where a real graph engine with traversal and pathfinding pays off, and it stays readable."

- **"How do you keep the two stores consistent?"**
  → "They never read from each other — both read from the **same conformed Silver layer**. So a shared-key metric, like 'shipments transiting Suez,' has to reconcile between the two stores by construction. That's our cross-store consistency check."

- **"What about scale / cost?"**
  → "We bounded AIS to 4 US ports, cargo+tankers, one quarter — ~1.9M rows — which still exercises partitioning, multi-port comparison, and temporal trends, but stays inside a $50/mo budget and ArangoDB CE's 100 GiB cap. Full global AIS is explicitly out of scope."

- **"What's actually built vs. proposed?"** *(likely, since the brief raises it)*
  → "The **`fact_voyage_leg` slice is built and runs end-to-end** — AIS → Silver → BigQuery via an Airflow DAG, idempotent, answering UC1 and UC2 in live SQL. The graph projection and the synthetic facts are designed and queryable on paper; building them is our next phase."

---

### Speaker timing recap

| Section | Target | Who |
|---|---|---|
| 1. Domain & goal | 1:00 | TBD |
| 2. Paradigm & schema | 2:00 | TBD |
| 3. Pipeline | 2:30 | TBD |
| 4. Tech stack | 1:00 | TBD |
| Buffer / transitions | 0:30 | — |

*Sources: `docs/deck/m1-*.md`, `docs/deck/m2-*.md`, `CLAUDE.md`. Slide content lives in the shared Google Slides deck — this is the spoken script behind it.*
