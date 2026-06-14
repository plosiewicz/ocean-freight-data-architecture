# Data Architecture Cheatsheet

The core concepts that shape this project, each with a plain-English definition and **how we use it here**. Read it top to bottom once; keep it open as a reference during the build and the pitch.

> Quick map of our stack to the jargon: **GCS** = the data lake / landing zone · **BigQuery** = the OLAP warehouse (star schema) · **ArangoDB** = the property graph · **Cloud Composer / Airflow** = the orchestrator.

---

## 1. Workload types — *what kind of questions am I asking?*

### OLTP — Online Transaction Processing
The "running the business" database: lots of tiny reads/writes, one row at a time, must be fast and correct for a single transaction. Think the booking app that inserts one new booking. Optimized for **writing**.
→ **In this project:** we do *not* build an OLTP system. A real forwarder's booking app would be OLTP; we treat its output as a *source* and model the analytical side.

### OLAP — Online Analytical Processing
The "understanding the business" database: a few huge reads that scan millions of rows to aggregate, trend, and slice. Optimized for **reading/analyzing**.
→ **In this project:** **BigQuery** is our OLAP store. It answers UC1 (ETA reliability) and UC2 (congestion) by crunching big piles of voyage/port-call rows.

### The one-line distinction
OLTP = *"change one record."* OLAP = *"summarize a billion records."* Different goals → different database designs. Forcing analytics onto an OLTP schema (or vice-versa) is the classic mistake this whole field exists to avoid.

### MPP — Massively Parallel Processing
The engine splits one query across many machines that each handle a slice, then combine results. It's why a warehouse can scan huge data fast.
→ **In this project:** BigQuery is serverless MPP — this is *why* our star-schema choices (below) pay off.

---

## 2. Dimensional modeling — *facts, dimensions, and the star*

This is the heart of the M2 deliverable.

### Fact table
A table of **events / measurements** — the things that happen, with numbers you want to aggregate. Usually long and skinny (many rows, few columns), and full of foreign keys pointing at dimensions.
→ **In this project:** `fact_voyage_leg`, `fact_port_call`, `fact_booking`, `fact_container_event`.

### Dimension table
A table of **reference info / context** — the "who, what, where, when" you filter and group *by*. Usually short and wide (fewer rows, descriptive columns).
→ **In this project:** `dim_date`, `dim_port`, `dim_vessel`, `dim_carrier`, `dim_lane`, `dim_commodity`.

### Measure
A numeric column in a fact table that you aggregate (sum, average, count).
→ **In this project:** `transit_hours`, `dwell_hours`, `schedule_delta_hours`, `booked_teu`.

### Grain
The precise meaning of *one row* in a fact table — stated as a single sentence. Picking the grain is the **first and most important** dimensional-modeling decision; everything else follows.
→ **In this project:** "one row per vessel per consecutive port-to-port leg" (`fact_voyage_leg`); "one row per vessel call at a port" (`fact_port_call`).

### Star schema
Facts in the center, dimensions around the edges, each fact joining *directly* to each dimension (one join hop). Drawn out, it looks like a star. Dimensions are kept **flat** (denormalized).
→ **In this project:** our entire BigQuery model. See `m2-bq-star.md`.

### Snowflake schema
A star where dimensions are **normalized** into sub-tables (e.g. `dim_port` → a separate `dim_country` table). Saves storage but adds join hops.
→ **In this project:** we deliberately **reject** snowflake. On a columnar engine storage is cheap and joins are the expensive part, so flattening wins. The defense is in `m2-star-vs-snowflake.md` — and "defending this choice" is exactly what we're graded on.

### Conformed dimension
A dimension defined **once** and shared consistently across multiple facts (same keys, same meaning). Lets you compare across business processes.
→ **In this project:** `dim_port` is used by both `fact_port_call` and `fact_container_event`; `dim_date` is shared by every fact. Same `port_id` means the same port everywhere.

### Date dimension
A pre-built calendar table (one row per day, with year/quarter/month/day-of-week columns) so time questions ("group by quarter") are simple joins instead of date math.
→ **In this project:** `dim_date`, generated once and never changed.

---

## 3. Keys — *how rows are identified and linked*

### Natural key (a.k.a. business key)
A real-world identifier that already exists in the domain.
→ **In this project:** **UN/LOCODE** (ports), **IMO** number (vessels), **SCAC** code (carriers), **HS code** (commodities).

### Surrogate key
A meaningless system-generated ID (usually an integer) used as the table's primary key, *instead of* relying on the natural key. Insulates the warehouse from messy/changing real-world codes and makes joins fast.
→ **In this project:** every dimension has a `<dim>_sk` (e.g. `port_sk`), and facts carry those `_sk` values as foreign keys.

### Why we keep both
The **surrogate** is the internal join key; the **natural** key is the bridge to the outside world — including our second database (see §7). Keeping both is standard warehouse practice.

---

## 4. Slowly Changing Dimensions (SCD) — *handling history*

Dimension attributes change over time (a vessel gets a new operator, a carrier rebrands). How you store that change is the SCD "type."

### SCD Type 1 — overwrite
Just replace the old value. No history kept. Simple; use when history doesn't matter.
→ **In this project:** `dim_port`, `dim_lane`, `dim_commodity` (if a port's attributes change, we overwrite).

### SCD Type 2 — add a new version row
Keep the old row, add a new one, and mark which is current (`effective_from` / `expiry_to` / `is_current` columns). Preserves full history so "what was true *then*?" still works.
→ **In this project:** `dim_vessel` and `dim_carrier` — a vessel's operator/flag change or a carrier's alliance change spawns a new version row.

*(There's also Type 0 = never changes, and Type 3 = keep only the previous value in an extra column. We only need Types 1 and 2.)*

---

## 5. Normalization, storage layout & performance

### Normalization vs. denormalization
**Normalize** = split data into many tables with no redundancy (great for OLTP writes). **Denormalize** = combine into fewer, wider tables with some repetition (great for OLAP reads).
→ **In this project:** flat (denormalized) star dimensions — the OLAP-friendly choice.

### Row storage vs. columnar storage
**Row store** keeps a whole record together (good for "fetch one row" = OLTP). **Columnar store** keeps each column together (good for "scan one column across millions of rows" = OLAP), and a query only reads the columns it touches.
→ **In this project:** BigQuery is columnar — so unused columns cost nothing to scan, which is the core of our star-over-snowflake argument.

### Partitioning
Physically splitting a big table into chunks (usually by date) so a query can skip ("prune") the chunks it doesn't need. The single biggest cost/speed lever for time-based questions.
→ **In this project:** facts are partitioned on their `*_date_sk` (a `YYYYMMDD` value), so "last quarter only" scans just those partitions.

### Clustering
Sorting/co-locating rows within a table by chosen columns so filters on them read less data. Complements partitioning.
→ **In this project:** each fact is clustered on its most-filtered foreign keys (e.g. `fact_port_call` on `port_sk, vessel_sk`).

### File formats: Parquet, JSONL, CSV
- **Parquet** — columnar, compressed, carries its own schema; the warehouse-friendly default for tabular data.
- **JSONL** (newline-delimited JSON) — one JSON object per line; good for nested/evolving event data.
- **CSV** — last resort: no schema, weak typing.
→ **In this project:** Parquet for AIS/reference/trade data, JSONL for synthetic events.

---

## 6. The pipeline — *getting data from source to served*

### ETL vs. ELT
**ETL** = Extract → Transform → *then* Load (clean before storing). **ELT** = Extract → Load → Transform (load raw, transform inside the warehouse). Modern cloud warehouses favor ELT.
→ **In this project:** we implement at least one cloud ETL/ELT slice (AIS → `fact_voyage_leg`).

### Data lake / landing zone
Cheap, durable object storage that holds **raw** data in its original form before any modeling. "Schema-on-read."
→ **In this project:** **GCS** is our data lake; the raw zone is treated as immutable.

### Bronze / Silver / Gold (the "medallion" tiers)
A common way to layer a lake: **Bronze** = raw as-landed; **Silver** = cleaned/conformed to canonical keys; **Gold** = business-ready (the served star / graph).
→ **In this project:** Phase 3 = Bronze (land raw), Phase 4 = Silver (conform), Phases 5–6 = Gold (BigQuery star + ArangoDB graph).

### Schema-on-write vs. schema-on-read
**On-write** = enforce structure when you store (warehouses). **On-read** = store anything, impose structure when you query (lakes).
→ **In this project:** GCS lake = schema-on-read; BigQuery warehouse = schema-on-write.

### Orchestration & DAGs (Airflow)
An **orchestrator** runs pipeline steps in the right order, on a schedule, with retries. A **DAG** (Directed Acyclic Graph) is the dependency graph of those steps — "do A and B, then C once both finish, with no loops."
→ **In this project:** **Cloud Composer** (managed **Airflow**) runs one DAG: `stage_conform` → (`load_bigquery` **and** `load_arango` in parallel) → `verify`.

### Idempotency
A load you can run repeatedly and always get the same end state (no duplicates). Achieved with deterministic keys + replace/upsert instead of blind insert.
→ **In this project:** loaders key on the natural keys so re-running a DAG is safe — important for demos.

---

## 7. The graph side — *relationships and paths*

### Property graph
Data modeled as **vertices** (nodes) and **edges** (relationships), where both can carry properties. Built for questions about *connections and paths*, which are painful as SQL joins.
→ **In this project:** **ArangoDB**. Vertices = `ports`, `vessels`, `carriers`, `lanes`, `chokepoints`; edges = routes/segments, `calls_at`, `transits_chokepoint`, `operated_by`.

### Vertex / edge / named graph
A **vertex** is a thing, an **edge** is a directed link between two vertices (has a `_from` and `_to`), and a **named graph** bundles the collections so you can traverse them as one network.
→ **In this project:** the named graph `ocean_network`.

### Traversal / shortest path
**Traversal** = walking the graph from a starting vertex following edges ("what does Suez connect to?"). **Shortest path** = the lowest-cost route between two vertices given edge weights.
→ **In this project:** AQL traversals + weighted `SHORTEST_PATH` answer UC3 (chokepoint exposure) and UC4 (rerouting).

### Why a graph *and* a warehouse (the hybrid argument)
Counting/trending questions are natural in a columnar warehouse; "what flows through this chokepoint / find me another route" questions explode into many self-joins in SQL but are one cheap traversal in a graph. Using **the right store per workload** — and proving it's justified, not incidental — is the project's central thesis.
→ **The glue:** both stores use the **same natural keys** (UN/LOCODE, IMO, SCAC), so a graph finding joins straight back to a warehouse fact. See `m2-conformed-keys.md`.

---

## 8. Cross-cutting concepts

### Entity-Relationship (ER) diagram & cardinality
A picture of entities and how they relate. **Cardinality** = how many of each side participate ("one vessel has many port calls"). The crow's-foot notation (the little forks) in our diagrams encodes one-to-one / one-to-many / many-to-many.
→ **In this project:** `m2-er-logical.md` is the ER diagram; `}o--||` means "many-to-exactly-one."

### Provenance / data lineage
Tracking where each row came from and how it was produced — essential when mixing real and synthetic data honestly.
→ **In this project:** every fact carries a `provenance` attribute marking it `real` or `synthetic`.

### Data governance
The rules around access, privacy, auditing, and anonymization of data.
→ **In this project:** mostly *out of scope* by design (basic IAM only), but worth naming as a real architectural concern.

---

## TL;DR table

| Concept | One-liner | Our example |
|---------|-----------|-------------|
| OLTP vs OLAP | Write-one vs analyze-many | (source app) vs BigQuery |
| Fact | Events with measures | `fact_voyage_leg` |
| Dimension | Reference context | `dim_port` |
| Grain | What one fact row means | "one vessel port-to-port leg" |
| Star schema | Flat dims around facts | the whole BQ model |
| Snowflake | Normalized dims (we reject it) | — |
| Conformed dim | Shared dim across facts | `dim_date` |
| Surrogate key | System ID for joins | `port_sk` |
| Natural key | Real-world ID / the bridge | UN/LOCODE, IMO, SCAC |
| SCD1 / SCD2 | Overwrite / keep history | `dim_port` / `dim_vessel` |
| Columnar | Scan columns, not rows | BigQuery |
| Partition / cluster | Skip + co-locate data | by date / by FK |
| ETL/ELT | Move + transform data | AIS → `fact_voyage_leg` |
| Bronze/Silver/Gold | Raw → conformed → served | GCS → Silver → BQ/Arango |
| DAG / Airflow | Ordered, scheduled steps | Composer pipeline |
| Property graph | Vertices + edges for paths | ArangoDB `ocean_network` |
| Hybrid | Right store per workload | BQ for counts, graph for routes |
