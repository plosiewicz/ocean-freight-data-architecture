# M3 Pitch — Spoken-Word Answers

> **Team Grilled Cheesin · MSDS 683.** Read-aloud scripts for the four M3 Midterm Design
> Pitch questions, plus short concept primers for likely Q&A. This is the *spoken* companion
> to `docs/deck/m3-pitch.md` (slide source of truth) and `docs/team-materials/m3-pitch-talking-points.md`.
> Every fact here traces to those files + `silver/identity.py` / `silver/imo.py`. Say it; don't read the slide.

---

## 1. Domain & Business Goal (~1 min)

> "We're **Grilled Cheesin** — PJ, Borna, and Alexander. Our domain is an **ocean freight
> forwarder**, basically a logistics middleman that books cargo onto container ships it
> doesn't actually own. Think of them as the broker between a company that needs to move
> goods and the carriers that have ships crossing the ocean.
>
> The business goal we built the architecture around is **risk and reliability**. A
> forwarder lives or dies on answering: *which routes and carriers are chronically late?
> Where are ports backing up? And what happens to my shipments if a chokepoint — Suez,
> Panama, the Strait of Malacca — suddenly closes?*
>
> We boiled that down to **four analytical questions**. Two are about reliability and
> congestion — worst-performing routes, and how dwell time at ports trends over time. The
> other two are network questions — what share of our shipments depend on Suez, and the best
> alternate route when a lane gets disrupted. And here's the thing that drives the whole
> design: **those four questions don't all want the same kind of database.** Hold that
> thought — it's the heart of our architecture."

---

## 2. Processing Paradigm & Schema Design (~2 min — graded core)

> "First, **OLAP, not OLTP.** We are not building a live booking system where someone
> reserves a container and we update a row. We're doing **read-heavy analytical queries**
> over historical movement data — averages, trends, comparisons across millions of
> vessel-position records. That's classic OLAP.
>
> For schema, we chose a **star schema, not snowflake.** Fact tables in the middle, flat
> dimension tables around them. We have **four fact tables** — `fact_voyage_leg` (a
> port-to-port hop with transit time, distance, and delay), `fact_port_call` (a port visit
> with dwell time), plus `fact_booking` and `fact_container_event`. Around those sit **six
> conformed dimensions** — date, port, vessel, carrier, lane, and commodity. That's **ten
> entities**, comfortably past the five-to-six bar.
>
> **Why star and not snowflake?** This is an engine-specific argument. BigQuery is a
> **columnar, massively-parallel engine**. On that kind of engine, *storage is cheap*,
> unused columns prune for free, and the **expensive operation is the join** — because joins
> shuffle data across compute slots. Snowflaking normalizes your dimensions to *save
> storage* — but that's row-store, OLTP-era thinking. On BigQuery, normalizing just buys you
> *more joins*, the one thing that actually costs you. Google's own guidance pushes even
> flatter. So a flat star is the sweet spot — defensible on cost, legible for grading.
>
> Two extra notes: we use **slowly-changing dimensions** — SCD type 2 on vessel and carrier
> (an operator or alliance can change and we want history), overwrite on the others. And
> every fact row carries a **provenance flag — real or synthetic** — so when we demo, we're
> honest about which numbers came from real AIS versus generated data.
>
> And the **second half of the schema story** is the graph. Those two network questions —
> reachability and shortest-path — are painful as recursive SQL but natural on a graph, so
> we run them on an **ArangoDB property graph**. The bridge that makes this *one*
> architecture and not two silos: **both stores share the same natural keys** — UN/LOCODE
> for ports, IMO for vessels, SCAC for carriers. A graph route is literally a list of port
> keys, so it joins one-to-one straight back to our warehouse facts, no fuzzy matching."

*(If drawing the schema: facts center, six dims radiating out, with `dim_date` / `dim_port`
/ `dim_vessel` shared across multiple facts — that shared-dimension overlap is what
"conformed" means.)*

---

## 3. Transformation Pipeline (~2–3 min — walk the arrows left to right)

> "Our pipeline is a **medallion architecture** — raw, then bronze, silver, gold. Left to right:
>
> **On the left, raw sources.** Real **AIS vessel-tracking** data in GeoParquet, port
> reference data with UN/LOCODE, chokepoint geometries, plus trade-flow indices. And a
> **synthetic generator** for the bookings and container events the real data doesn't give us.
>
> **First transformation — Raw to Bronze:** we land everything *exactly as it arrives*,
> immutable, partitioned by date. Critically, we **bound the AIS** to a defensible slice —
> four US ports, cargo and tankers only, about 31 days, roughly **1.9 million position
> rows** — not the whole planet. That keeps us honest on cost and scope.
>
> **The critical step — Bronze to Silver — is where the real work happens.** Three
> transforms: first, we **resolve MMSI to IMO** — MMSI is a transient radio ID, IMO is the
> permanent hull identity, so we tie-break and count collisions to get clean vessel
> identity. Second, we **geofence** — figure out which port a ship is visiting from its
> actual *geometry*, not the unreliable free-text destination field, and that produces
> port-calls. Third, we **pair those calls into voyage legs** — each leg gets a transit
> time, distance, and delay — then **conform everything to the shared natural keys and stamp
> the provenance flag.**
>
> **Last step — Silver to Gold — is the key design move: one conformed source, two sinks.**
> That single Silver layer is the source of truth. From it we fan out *in parallel*: we load
> the **star schema into BigQuery**, partitioned and clustered, and we project the **same
> entities into the ArangoDB graph**. Because both Gold stores read from Silver and *never
> from each other*, they reconcile by construction — the warehouse and the graph can't
> drift apart. The whole thing is **orchestrated by an Airflow DAG.**
>
> Built-vs-designed honesty: the **`fact_voyage_leg` path into BigQuery is built and runs
> end-to-end today** — AIS through Silver into BigQuery, via the Airflow DAG, idempotent,
> answering our reliability questions in live SQL. The graph load and synthetic facts are
> **designed and queryable on paper** — that's the next phase. *Here's the full design, and
> here's the slice we already proved.*"

---

## 4. Early Tech Stack & Cost Posture (~1 min)

> "Quick tour of the stack, bottom to top:
>
> - **Storage** is a **Google Cloud Storage** data lake — Parquet for tabular, JSONL for events.
> - **Orchestration** is **Apache Airflow 3.0**. One cost note we'll defend: we run **plain
>   Airflow on a small VM, not managed Cloud Composer** — Composer can't scale to zero and
>   runs $300+ a month. The rubric requires *Airflow*, not Composer specifically, and our
>   setup is Composer-portable if we ever need it.
> - **OLAP warehouse** is **BigQuery** — the star schema, native partitioned + clustered tables.
> - **Graph store** is **ArangoDB 3.12**, a managed cluster. One reality: Pregel was removed
>   in 3.12, so our graph analytics use **AQL traversals and weighted shortest-path** instead
>   — plenty for our scale.
> - **Data generation** is **Python — Faker and NumPy, fully seeded**, so the whole dataset
>   is byte-for-byte reproducible from a clone; we commit a checksum to prove it.
>
> On **cost posture**: that bounded AIS slice keeps us inside a **$50/month budget**, with
> alerts at 50, 90, and 100 percent. And this architecture is deliberately **designed to
> extend into a Data Lakehouse** for our MSDS 681 build next term — future work, not built here."

---

## Concept primers (for Q&A)

### What is a "medallion architecture"?
A way of organizing a pipeline into **tiers of increasing cleanliness** — **Bronze → Silver
→ Gold** (like medals; bronze is rawest). **Bronze** = raw, as-it-arrived, immutable.
**Silver** = cleaned, conformed, identities resolved, shared keys agreed — the trustworthy
single source of truth. **Gold** = serving layer shaped for the use cases (our BigQuery star
+ ArangoDB graph). It's a naming convention and discipline, not a product. Each layer is
persisted, so any downstream layer can be rebuilt from an upstream one. Our payoff:
**"one conformed Silver layer, two sinks"** — BigQuery and ArangoDB can never disagree
because both are built from the same Silver.

### What does "bound the AIS to a defensible slice" mean?
**AIS** = Automatic Identification System; every commercial ship broadcasts position, speed,
heading, and ID over radio. The *full global* feed is billions of rows — too big and too
expensive for a course project. So we deliberately cut it to a justified subset: **4 US
ports, cargo + tankers only, ~31 days ≈ 1.9M rows.** "Defensible" is the graded part — the
slice still exercises every architectural feature (partitioning, clustering, geofencing, the
two-store join), and the analytical story doesn't need the whole planet to be valid.

### How did we actually map MMSI → IMO?  (`silver/identity.py`, `silver/imo.py`)
Two different ship IDs: **MMSI** is what the AIS radio broadcasts, but it's tied to the
*registration* and can change if a ship is sold or re-flagged — transient and unreliable.
**IMO** is welded to the hull, never changes — the true identity. AIS *position* messages
carry MMSI but usually a null/0 IMO; only static (Type-5) messages carry the IMO. Our resolution:

1. **Validate the IMO with a check-digit** (`valid_imo`) — must be exactly 7 digits passing
   the IMO checksum; rejects MMSI-in-IMO-field, typos, and the `0000000` padding sentinel.
2. **Collect only valid IMOs per MMSI**, then **broadcast** that IMO to the same MMSI's
   IMO-less position rows.
3. **Tie-break collisions** — if one MMSI maps to more than one valid IMO (reassignment or
   spoofing in the slice), pick the **most-frequent IMO, then latest-seen by timestamp**,
   and increment a **collision counter**.
4. **Report drops and collisions as first-class data-quality metrics** — MMSIs that never
   carried a valid IMO anywhere are dropped from the real facts and counted.

The philosophy worth saying out loud: the resolution **doesn't hide its uncertainty** — it
*counts* collisions and no-IMO drops and surfaces them as DQ numbers, the same honest-data
theme as the `real | synthetic` provenance flag. The core `resolve_mmsi_to_imo` is a pure,
offline-unit-tested function, separate from the Bronze reader.
