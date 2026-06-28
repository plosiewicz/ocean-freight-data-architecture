# BigQuery

**Layer:** OLAP store — the star-schema warehouse (`ofa_star`) that answers UC1 + UC2.

## What it does
BigQuery is GCP's serverless, columnar, massively-parallel SQL warehouse. No cluster to size or run;
you pay for bytes stored and bytes **scanned**. We model a **star schema**: two date-partitioned,
clustered facts (`fact_voyage_leg`, `fact_port_call`) surrounded by flat conformed dimensions
(`dim_vessel`, `dim_port`, `dim_carrier`, `dim_lane`, + `operated_by` bridge).

## Role in our project
- Serves the **OLAP use cases**: **UC1 ETA reliability** (`sql/uc1_eta_reliability.sql`) and **UC2
  port congestion / dwell trend** (`sql/uc2_dwell_trend.sql`) — group-average-compare-trend roll-ups.
- Loaded from Silver Parquet via the Airflow DAG's `load_bigquery` leg (`GCSToBigQueryOperator`,
  `WRITE_TRUNCATE` per partition; SCD2 dims via staging→`MERGE`). DDL in `sql/ddl_star.sql`.
- Facts **partition on `dt`** and **cluster on the FKs queried most** — partition pruning is the
  primary cost lever.
- The web dashboard reads it live via `@google-cloud/bigquery`, with frozen-golden fallback.

## Why it's the best option here
- **Serverless** — the rubric and our budget both reward "no cluster to run." We provision nothing
  and idle cost is storage-only.
- **Columnar + partition pruning makes the star schema pay off.** On a columnar engine, unused columns
  prune for free and joins are the expensive part — so flat dimensions (star) beat normalized ones
  (snowflake). That's the defended schema decision, and BigQuery is what makes it true.
- **Native GCS loads** — Parquet maps cleanly to BQ types; the load path is a provider operator, not
  bespoke code.
- **Free-tier friendly** at course scale — demo scans are effectively $0.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| Snowflake (the product) | Another excellent columnar warehouse, but off the GCP credits; no advantage for our workload | Multi-cloud or existing Snowflake shop |
| PostgreSQL / a row store | Row-store, OLTP-shaped; aggregations over millions of rows scan everything and joins/indexing become the bottleneck | Transactional workloads, not analytical roll-ups |
| DuckDB | Great single-node analytics, but not a shared, durable, cloud warehouse for a team demo | Local analysis / embedded OLAP |
| Snowflake-schema (normalized dims) in BQ | Adds join cost on an engine where storage is cheap and columns prune free — wrong trade | A genuinely huge, slowly-changing, shared dimension (none of ours qualify) |
| BQ external tables over GCS | Slower per-query (reads GCS at query time); we load native once for the demo | "Query raw without loading" teaching aside |

## Likely Q&A
- *"Star or snowflake, and why?"* — **star.** Columnar storage is cheap and prunes unused columns;
  joins are the cost. Normalizing to save storage is row-store thinking. Full rationale:
  `m2-star-vs-snowflake.md`.
- *"How do you control cost?"* — partition on `dt` (pruning), cluster on high-selectivity FKs, load
  native Parquet. Bytes scanned is the bill, so the physical design *is* the cost model.
- *"How are updates handled?"* — SCD2 dims load staging→`MERGE` (idempotent); facts `WRITE_TRUNCATE`
  per `dt` partition, so a re-run replaces identical bytes.
