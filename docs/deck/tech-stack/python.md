# Python 3.11

**Layer:** the language for all ingestion, synthetic generation, conform/derive transforms, and glue.

## What it does
Python is the implementation language for everything between the sources and the stores: pulling real
data, generating synthetic data, the geo-fence state machine, the fact derivations, the priors
conditioner, and the idempotent loaders.

## Role in our project
- `ingest/` (real-source pulls), `data_gen/` (seeded synthetic generators), `silver/` (identity
  resolution, geo-fencing, dims, facts), `analytics/` (UC3/UC4 runners), `lib/` (GCS / Arango /
  loaders), `dags/` (the Airflow DAG), `scripts/` (landing, verify, freeze).
- Pinned to **3.11** to match the Cloud Composer 3 / Airflow 3 worker runtime, so local and
  (eventual) managed execution don't drift.

## Why it's the best option here
- **It's the lingua franca of the whole stack** — Airflow DAGs, the GCP client libraries, python-arango,
  pandas/pyarrow, NumPy, and Faker are all Python. One language end to end, no FFI seams.
- **Pinning 3.11 to the Composer runtime** removes a whole class of "works locally, breaks in the
  cloud" bugs.
- The transform logic (state machine, conditioning math) is naturally expressed and **unit-testable
  offline** as pure functions.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| SQL-only (BQ) transforms / dbt | Adds a transform framework; the geo-fence state machine and conditioning math aren't SQL-shaped | Pure warehouse-side transforms (revisit for the MSDS 681 lakehouse) |
| Scala/Java + Spark | Heavy cluster framework; unjustified at a bounded course slice | True big-data ETL (100s of GB–TB streaming) |
| JavaScript/TypeScript | Great for the web app (we use it there), but the data stack's libraries are Python-first | Front-end / Node services |
| Python 3.12 | Fine, but we pin 3.11 to match the Composer worker exactly | When the managed runtime moves to 3.12 |

## Likely Q&A
- *"Why 3.11 specifically?"* — to match the Cloud Composer 3 / Airflow 3 worker, avoiding local/remote
  version drift.
- *"Why not push transforms into SQL?"* — UC1/UC2 *are* SQL; but the event-detection (geo-fence) and
  edge-weight conditioning are imperative, stateful logic that belongs in tested Python, not a query.
