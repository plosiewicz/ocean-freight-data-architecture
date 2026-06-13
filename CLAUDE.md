# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This is a **greenfield academic project** with no code yet. The repository currently contains only `docs/Project plan.pdf` — the assignment brief for **MSDS 683 (Data Architecture)**, a 3-person group project. There is no git repo, build system, or test suite initialized. When asked to scaffold or implement, start from the requirements below; do not assume existing tooling.

## What this project must deliver

The goal is to design and partially implement a **complete end-to-end data architecture** for a self-chosen domain. The deliverable is graded across milestones (100 pts + 20 bonus), culminating in a working demo. Key technical requirements that constrain all design decisions:

- **Dimensional modeling**: produce an ER diagram (5–6+ entities), then classify entities into **fact vs. dimension** tables. Schema-design tradeoffs (star vs. snowflake, OLAP vs. OLTP) must be made *and defended* — capture the rationale, not just the choice.
- **At least one cloud ETL process** must be designed and implemented (not just diagrammed).
- **Airflow** orchestrates the pipeline. DAGs are the expected orchestration layer.
- The chosen domain should exhibit 1–3 of: multi-source/multi-format data (structured tables + semi-structured JSON/Parquet + unstructured text/logs/images), large scale (100 GB–TBs, or defensible scaling decisions), governance/security constraints (access control, auditing, anonymization), or temporal richness (event streams, daily transactions, sensor readings).
- **Data sourcing**: start from a real public dataset; augment with synthetic data where the real data doesn't satisfy chosen constraints.

## Architectural decisions to record

Because grading rewards *defending* design choices, every significant decision should be documented with its tradeoff reasoning (ideally as an ADR or in the slide deck): domain + 3–4 analytical use cases, fact/dimension assignments, star vs. snowflake, OLAP vs. OLTP, choice of cloud platform for ETL, and how scale/governance/temporality requirements are satisfied. This architecture is also intended to seed a Data Lakehouse build in MSDS 681 next term, so favor designs that extend to a lakehouse.

## Milestones (drives sequencing)

1. **M1 — Domain & Dataset**: lock domain, analytical questions, and data sources.
2. **M2 — Domain Model**: ER diagram + fact/dimension first pass; reconcile data needs against available sources.
3. **M3 — Midterm Design Pitch**: ~7 min presentation.
4. **M4 — GitHub Repo**: the repo + a checklist of its contents (this is when code/infra is expected to land).
5. **Final**: ~10 min presentation with a working demo.

All milestones accumulate in a single Google Slides deck (not separate decks).

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Ocean Freight Forwarder Data Architecture (MSDS 683)**

An end-to-end data architecture for a **freight forwarder / 3PL** operating in **global ocean container logistics**. Multi-source, multi-format maritime data (real AIS vessel tracking + port reference + trade-flow data, augmented with synthetic bookings and container events) flows through a GCP pipeline into a **hybrid analytical layer**: a BigQuery star-schema warehouse for OLAP/dimensional analytics and an ArangoDB property graph for network/relationship analytics.

This is the group deliverable for **MSDS 683 (Data Architecture)** — graded on translating a domain into a data model, making and *defending* schema design decisions, implementing at least one cloud ETL process, orchestrating with Airflow, and demoing it. It is also intended as the design foundation for the **MSDS 681 (Data Lakehouse)** build next term.

**Core Value:** The architecture must answer the four freight-forwarder analytical questions through the **right store per workload** — OLAP questions on a defended BigQuery star schema, network questions on the ArangoDB graph — proving that the hybrid design is justified rather than incidental.

### Constraints

- **Timeline**: Course milestones M1 → M2 → M3 (midterm pitch) → M4 (GitHub repo) → Final demo. **Front-load M1 + M2 (all design) as Phases 1–2, before any implementation.**
- **Team**: 3 students (names + food-themed team name finalized in M1).
- **Tech stack**: ArangoDB (graph store), GCP — GCS (raw landing) + Cloud Composer (managed Airflow) + BigQuery (star-schema warehouse).
- **Budget**: GCP credits — prefer managed services already covered; avoid runaway compute (e.g., bound AIS volume to a defensible slice).
- **Deliverable format**: single Google Slides deck across all milestones (do not create new decks); working demo for the final.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## TL;DR — The Prescriptive Stack
| Layer | Choice | One-line rationale |
|-------|--------|--------------------|
| Raw landing | **GCS** with Hive-style date partitioning, **Parquet** for tabular (AIS/port/trade), **JSONL** for synthetic events | Columnar + cheap; JSONL only where schemas are evolving or JSON-typed |
| Orchestration | **Cloud Composer 3** running **Airflow 3.x** (3.0 GA; 3.1 in preview) | Rubric requires managed Airflow; CC3 is GA and the only forward-supported track |
| OLAP store | **BigQuery**, native tables, **star schema**, date-**partitioned** + **clustered** | Columnar engine; star is the defended pattern, not snowflake |
| Graph store | **ArangoDB 3.12.6** Community Edition (single node) | CE now ships all Enterprise features ≤100 GiB; matches author expertise |
| Graph load | **arangoimport** (idempotent) + **python-arango 8.x** loaders | CLI for bulk, driver for orchestrated/idempotent loads |
| Graph analytics | **AQL** traversals/pathfinding + **client-side NetworkX / nx-arangodb** for PageRank/centrality | **Pregel was REMOVED in 3.12** — must substitute |
| Synthetic data | **Faker** (seeded) + **NumPy** default_rng + **pandas/pyarrow** | Deterministic reproducibility; writes Parquet/JSONL directly |
| Sync glue | One Composer DAG, two load tasks from the **same conformed staging layer** | Single source of truth → fan-out to BQ and Arango |
## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Google Cloud Storage** | n/a (service) | Raw + staging landing zone (data lake) | Cheapest durable object store on GCP; the de-facto landing zone Composer/BigQuery both read natively. Use as the single immutable raw tier. |
| **Cloud Composer 3** | GA (Mar 2025); Airflow **3.0** (GA) / **3.1** (preview) | Managed Airflow for batch ETL orchestration | Rubric *requires* managed Airflow. CC3 is the only forward-supported generation — CC1 creation stopped Sep 15 2025; CC1 and CC2 2.0.x reach EOL Sep 15 2026. Pin to a CC3 image with Airflow 3.0 for stability (3.1 still preview as of mid-2026). |
| **BigQuery** | n/a (service) | OLAP / dimensional warehouse (star schema) | Serverless columnar MPP. Native tables + partition pruning + clustering give cheap-storage / cheap-scan economics that make the star-vs-snowflake argument (below) defensible. |
| **ArangoDB Community Edition** | **3.12.6.x** (latest stable, Nov 2025) | Native property-graph store for network/relationship use cases | Multi-model graph store; matches the team's domain expertise (author is ArangoDB SE/SA). **From 3.12.5 CE includes all Enterprise features with no time limit, capped at 100 GiB** — perfect for a course-scale bounded dataset, free, no license friction. Run single-node (no cluster) for the project. |
| **Python** | **3.11** or **3.12** | Synthetic generation, loaders, glue | Composer 3 / Airflow 3 images and the GCP + Arango client libraries all target modern 3.x. Pin 3.11 to match the Composer worker runtime to avoid local/remote drift. |
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **python-arango** | **8.3.x** (Mar 2026) | Official ArangoDB driver | Idempotent loaders, collection/index/graph creation, AQL execution from DAGs and generators. The substrate for the "idempotent loader" pattern reused from the Brambles prior art. |
| **google-cloud-bigquery** | 3.x | BQ jobs from Python/DAGs | Programmatic load jobs, query execution, table/partition management when not using the Airflow operators. |
| **google-cloud-storage** | 2.x / 3.x | GCS object I/O | Upload generated Parquet/JSONL to the raw zone; list/verify for ship-gate checks. |
| **pandas** | 2.x | Tabular shaping of real + synthetic data | Building dimension/fact frames before writing Parquet; light transforms in generators. |
| **pyarrow** | 16.x+ | Parquet read/write, BQ-compatible types | Write partitioned Parquet to GCS; the canonical engine behind `pandas.to_parquet`. |
| **NumPy** | 2.x | Seeded random distributions for synthetic events | `numpy.random.default_rng(seed)` for reproducible dwell-times, delays, booking volumes. |
| **Faker** | 25.x+ | Synthetic identifiers/text (carrier names, booking refs, addresses) | `Faker.seed(N)` for deterministic runs. **Pin to the patch version** — Faker explicitly does not guarantee output stability across patches. |
| **nx-arangodb** | latest (RTD-published) | NetworkX backend persisting to/from ArangoDB | Run PageRank / centrality / community detection against graph data after Pregel's removal — client-side `nx.pagerank(G)`, server-side traversals where supported. |
| **networkx** | 3.x | Graph algorithms (PageRank, Adamic–Adar link prediction) | The Pregel/GraphSAGE substitute for a course-scale (≤ a few 100K edge) graph. CPU is sufficient at this scale; `nx-cugraph` GPU backend is available but **not needed** here. |
| **Apache Airflow providers (Google)** | bundled with CC3 image | `GCSToBigQueryOperator`, `BigQueryInsertJobOperator`, `BashOperator` for arangoimport | DAG authoring — prefer provider operators over raw client calls for the BQ load leg. |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| **arangoimport** | Bulk load vertices/edges into Arango | 3.12 default `--type auto` (detects by extension); use `arangoimport`, **not** the deprecated `arangoimp`. Drive from a `BashOperator` or Make target. |
| **bq CLI** | Ad-hoc loads, schema inspection, dataset/table DDL | `bq load --source_format=PARQUET` (or `NEWLINE_DELIMITED_JSON`); useful for the one implemented slice before fully wiring operators. |
| **gcloud / gsutil** | Bucket/IAM setup, object copy | Basic IAM only (governance is explicitly out of scope). |
| **Makefile** | Verb-script entrypoints (`make generate`, `make load-bq`, `make load-arango`, `make verify`) | Reuse the Brambles Make-target + ship-gate verification pattern — proven, idempotent, demo-friendly. |
| **ArangoDB Web UI / arangosh** | Graph visualization for the demo, ad-hoc AQL | Web UI graph viewer doubles as the "graph visualizer" the demo needs without a separate UI build. |
## Detailed Prescriptions (answers to the six sub-questions)
### 1. GCS landing conventions & file formats
- **Parquet** for AIS, port reference, and trade flows — columnar, compressed, schema-embedded, and the **recommended external-table / load format** for BigQuery. Best scan economics and clean type mapping.
- **JSONL (NEWLINE_DELIMITED_JSON)** for synthetic bookings/container events — schema is yours and may evolve, and JSON-typed columns cannot round-trip through Parquet loads, so JSONL is the safe default for nested/evolving event records.
- **CSV** only as a last resort for a raw source that arrives that way (some UNCTAD/World Bank extracts); convert to Parquet at the staging step rather than loading CSV into BQ.
- Treat the raw zone as **immutable**; write a separate `staging/` prefix for conformed/cleaned Parquet that both BQ and Arango loaders consume. This is the linchpin of the two-store sync (see §5).
### 2. Cloud Composer / Airflow version & DAG conventions
- **Use Cloud Composer 3 with Airflow 3.0 (GA).** Avoid 3.1 (preview as of 2026) for a graded deliverable. Do **not** start on CC2 — it is on the EOL path (Sep 15 2026).
- **DAG authoring conventions:**
### 3. BigQuery dimensional modeling & loading
- **Star schema, native tables.** Fact tables (`fact_voyage_leg`, `fact_port_call`, `fact_shipment_event`) + conformed dimensions (`dim_vessel`, `dim_port`, `dim_carrier`, `dim_lane`, `dim_date`).
- **Partition** fact tables on the event/date column (`DATE(event_ts)` or an ingestion date) — partition pruning is the single biggest cost lever for the temporal use cases (ETA reliability, congestion over time).
- **Cluster** facts on the high-selectivity foreign keys queried/filtered most (e.g. `port_id`, `carrier_id`, `vessel_id`) — keep to **≤4 cluster keys**.
- **Native, not external, tables** for the served star schema: external tables read from GCS at query time and are slower; load once into native storage for the demo. Keep external tables only as an optional "query raw without loading" teaching aside.
- **Load mechanism:** `GCSToBigQueryOperator` with `source_format=PARQUET` and `WRITE_TRUNCATE` per partition (Parquet) or `NEWLINE_DELIMITED_JSON` for the synthetic JSONL. Prefer **explicit schemas** over autodetect for dimensions to lock types.
- **Star vs snowflake (the defended decision):** BigQuery is a columnar MPP engine — **storage is cheap, unused columns are pruned for free, and joins are comparatively expensive**. Snowflaking normalizes dimensions to save storage, which is OLTP/row-store-era reasoning that does not pay off here; it just adds join cost and query complexity. Keep dimensions flat (star); only snowflake a dimension if it is genuinely large, slowly-changing, and shared in a way that makes the redundancy costly — none of the ocean-freight dimensions here qualify. (Google's own guidance even permits *denormalizing further* into nested/repeated fields, but star keeps the model legible for a course deliverable while staying BigQuery-idiomatic.)
### 4. ArangoDB graph loading & analytics
- **Collections / naming:** vertex collections `vessels`, `ports`, `carriers`, `lanes`; edge collections `voyage_leg` (port→port), `operated_by` (vessel→carrier), `calls_at` (vessel→port). Use a single **named graph** `ocean_network` so AQL traversals and the Web UI visualizer work out of the box.
- **`_key` discipline:** deterministic, source-derived keys (e.g. UN/LOCODE for ports, IMO for vessels) so loads are idempotent and edges resolve `_from`/`_to` reliably.
- **Loading:** `arangoimport` for bulk vertex/edge files (3.12 auto-detects type by extension; `--on-duplicate replace` for idempotency). For orchestrated/conditional loads, **python-arango 8.x** loaders that create collections, ensure indexes, and upsert from the same staging Parquet/JSONL.
- **Indexes:**
- **Analytics — IMPORTANT version change:** **Pregel (algorithms, JS API, HTTP API) was REMOVED entirely in ArangoDB 3.12.** The Brambles prior art's "Pregel PageRank" pattern **will not run on 3.12** and must be substituted:
### 5. Keeping the two stores in sync from the same ETL
- **Single conformed staging layer is the contract.** Both load legs read the **same `staging/` Parquet/JSONL**, so BigQuery facts/dims and Arango vertices/edges are derived from one cleaned source — not two divergent transforms.
- In the Composer DAG, `stage_conform` produces staging; `load_bigquery` and `load_arango` are **parallel downstream tasks** depending on it, followed by a `verify` task asserting row/vertex/edge counts reconcile (the Brambles ship-gate pattern).
- **Shared keys across stores:** the same deterministic business keys (UN/LOCODE, IMO, carrier code) are the BQ dimension surrogate-key *natural keys* and the Arango `_key`s — this is what lets a graph result join back to a BigQuery fact in the demo narrative.
- Use **batch full-partition reload** for idempotency rather than incremental CDC — streaming/CDC is explicitly out of scope and unnecessary for the analytical use cases.
### 6. Python synthetic-data tooling (deterministic)
- **`numpy.random.default_rng(SEED)`** for all distributional draws (delays, dwell times, booking counts) — modern, reproducible Generator API.
- **`Faker` with `Faker.seed(SEED)`** for identifiers/labels (carrier names, booking references). **Pin Faker to an exact patch version** — output is not guaranteed stable across patches.
- A central `SEED` constant + per-entity `seed_instance()` for independent reproducible streams; write outputs as **partitioned Parquet (tabular) / JSONL (events)** straight to the GCS raw zone via `pyarrow` + `google-cloud-storage`.
- Mirror the Brambles generator/loader split: generators are pure (seed → files), loaders are idempotent (files → store).
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Cloud Composer 3 / Airflow 3.0 | Self-hosted Airflow / Astronomer | If GCP credits were unavailable; not the case here, and rubric wants managed Airflow. |
| BigQuery native star tables | BigQuery external tables over GCS | Teaching aside, or if the dataset were genuinely too large/transient to load — not so for a bounded course slice. |
| Star schema (flat dims) | Denormalized nested/repeated single table | If a dimension is purely hierarchical and always queried with its fact; star is more legible for grading. |
| AQL + client-side NetworkX | ArangoDB Data Science Service / GraphML | If you needed managed, scalable distributed PageRank/embeddings — overkill and added cost for course scale. |
| `arangoimport` + python-arango | ArangoDB Datastore / Spark connector | Big-data ingest scenarios; unnecessary at ≤100 GiB CE scale. |
| Faker + NumPy | SDV / Gretel (statistical synthesizers) | If you needed to learn joint distributions from real data; here scripted generators give more control and determinism. |
| NetworkX PageRank | nx-cugraph (GPU) | Graphs in the tens-of-millions of edges; not this project. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **ArangoDB Pregel (PageRank, community detection)** | **Removed entirely in 3.12** — code from the Brambles prior art will not run | AQL traversals/shortest-path for reachability; client-side NetworkX (`nx-arangodb`) for PageRank/centrality |
| **GraphSAGE / GNN link prediction** | Requires a PyTorch Geometric/DGL training stack; disproportionate for a 3-person term project | Adamic–Adar heuristic in NetworkX (document GraphSAGE as future work) |
| **Snowflake schema on BigQuery (by default)** | Normalization-to-save-storage is row-store thinking; adds join cost on a columnar engine where storage is cheap and columns prune free | Star schema with flat dimensions |
| **Dataflow / Apache Beam** | Heavy streaming/transform framework; operational overhead unjustified for batch ETL at course scale | Composer + BigQuery SQL + Python transforms |
| **dbt** | Adds a transform framework + project scaffolding; transform complexity here doesn't demand it | SQL in `BigQueryInsertJobOperator` tasks; revisit for the MSDS 681 lakehouse |
| **Cloud Composer 1 / CC2 2.0.x** | EOL Sep 15 2026; CC1 creation already disabled | Cloud Composer 3 |
| **Airflow 3.1 in production grade** | Still preview as of 2026 | Airflow 3.0 (GA) on CC3 |
| **CSV into BigQuery as the served format** | No schema embedding, weak typing, slow parse | Convert to Parquet at staging; JSONL only for JSON-typed events |
| **`arangoimp` executable** | Deprecated alias | `arangoimport` |
| **Real-time / streaming ingestion** | Adds Pub/Sub + streaming inserts complexity without serving any of the four use cases | Batch full-partition reload |
## Stack Patterns by Variant
- Land AIS as partitioned Parquet (`dt=`), conform to `fact_port_call` + `dim_port` (geo), load BQ native + Arango `ports`/`calls_at`.
- Because it exercises partitioning, clustering, geo indexing, and the two-store sync in one vertical slice — maximal rubric coverage per unit of build.
- Lead with AQL shortest-path and `GEO_DISTANCE` chokepoint queries in the Arango Web UI visualizer; use BQ only to source the dimensions.
- Because AQL pathfinding is unaffected by the Pregel removal and is the strongest, lowest-risk graph demo.
- Bound to a defensible slice (one region/quarter, downsampled positions) at staging before load.
- Because CE caps at 100 GiB and BQ scan costs scale with bytes; the analytical story doesn't need the full 100GB+ corpus.
## Version Compatibility
| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Cloud Composer 3 | Airflow 3.0 (GA), 3.1 (preview) | Pin a specific CC3 image; verify the bundled Google providers version for operator signatures. |
| python-arango 8.3.x | ArangoDB 3.12.x | Driver 8.x targets the current 3.12 HTTP API. |
| ArangoDB 3.12.5+ CE | all Enterprise features, ≤100 GiB | Free, non-commercial, no time limit — sufficient for the bounded dataset. |
| Faker (pinned patch) | Python 3.11/3.12 | Pin exact patch — output not stable across patch versions. |
| pyarrow 16.x+ | pandas 2.x, BigQuery Parquet loads | Type mapping clean for Parquet; avoid JSON-typed columns in Parquet (use JSONL). |
| NumPy 2.x | pandas 2.x | Confirm any generator deps support NumPy 2 ABI. |
## Sources
- https://docs.cloud.google.com/composer/docs/composer-versions — CC3 GA, Airflow version support windows, CC1/CC2 EOL dates (HIGH)
- https://cloud.google.com/blog/products/data-analytics/cloud-composer-supports-apache-airflow-31 — Airflow 3.1 preview on Composer (HIGH)
- https://docs.arango.ai/arangodb/3.12/release-notes/deprecated-and-removed-features/ — Pregel removal in 3.12; arangoimp deprecation; arangoimport `--type auto` (HIGH)
- https://arangodb.com/3-12-ce-changes-faq/ — CE includes Enterprise features ≤100 GiB from 3.12.5 (HIGH)
- ArangoDB 3.12.6.x latest stable (Nov 2025) — release-notes / downloads (HIGH)
- https://github.com/arangodb/python-arango/releases — python-arango 8.3.1 (Mar 2026) (HIGH)
- https://github.com/arangodb/nx-arangodb + https://nx-arangodb.readthedocs.io/ — NetworkX-over-Arango, client-side PageRank (MEDIUM)
- https://developer.nvidia.com/blog/accelerated-production-ready-graph-analytics-for-networkx-users/ — nx-cugraph backend, ~60 algorithms incl. PageRank (MEDIUM, GPU not used here)
- https://docs.arangodb.com/3.12/index-and-search/indexing/working-with-indexes/geo-spatial-indexes/ + .../aql/functions/geo/ — geo/persistent indexes, GEO_DISTANCE/NEAR (HIGH)
- https://docs.cloud.google.com/bigquery/docs/best-practices-performance-nested + clustered-tables + loading-data-cloud-storage-json — denormalize/star guidance, partition+cluster, Parquet-recommended, JSONL for JSON columns (HIGH)
- https://github.com/joke2k/faker — Faker.seed determinism, patch-pin caveat (HIGH)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
