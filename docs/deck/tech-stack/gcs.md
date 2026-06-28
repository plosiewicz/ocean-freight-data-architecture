# Google Cloud Storage (GCS)

**Layer:** raw (Bronze) + conformed (Silver) landing zone — the data lake floor.

## What it does
GCS is GCP's durable object store: cheap, effectively unlimited buckets of immutable blobs. We use
it as the **landing zone** both ETL and the warehouse read natively. Objects are written under
Hive-style date-partitioned prefixes (`ais/dt=2024-01-31/…`), as **Parquet** for tabular sources and
**JSONL** for evolving synthetic events.

## Role in our project
- **Bronze** (`…-bronze` bucket): raw, immutable copies of every source exactly as pulled — real AIS,
  WPI/UN-LOCODE reference, LSCI/Comtrade/LPI priors, and the synthetic generator output.
- **Silver** (under a `silver/` prefix in the same bucket): the **single conformed source of truth**
  (`dim_*.parquet`, `fact_*/dt=…`) that *both* Gold stores read. This is the linchpin of the
  "one transform, two sinks" contract — BigQuery and ArangoDB load from the same Silver, never from
  each other.
- Read/written via `lib/gcs.py` and `google-cloud-storage`; `scripts/verify.py` lists/reads it for
  the ship-gate row-count checks.

## Why it's the best option here
- **It's the native landing zone for the rest of the stack.** BigQuery loads directly from GCS
  (`GCSToBigQueryOperator`), and Cloud Composer/Airflow read it without glue. Picking anything else
  would add an export/copy step for zero benefit.
- **Cheapest durable tier** — storage is ~$0.02/GB/mo; at our bounded slice this rounds to nothing,
  and it keeps the "storage is cheap, scanning is the cost" economics that justify the star schema.
- **Immutability is a design feature** — treating Bronze as write-once makes re-runs reproducible and
  gives us a clean audit trail (raw is never mutated; conforming writes a separate prefix).

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| AWS S3 / Azure Blob | Equivalent object store, but off-platform — we're all-in on GCP credits and BQ/Composer read GCS natively | If the warehouse/orchestrator lived on AWS/Azure |
| BigQuery as the only tier (no lake) | Loses the immutable raw audit trail and the shared Silver that feeds the graph; couples the graph load to BQ | If there were no second (graph) sink |
| Local disk / committed data | Not durable, not shareable across a 3-person team, doesn't scale | Tiny throwaway experiments |
| HDFS / a lakehouse table format (Iceberg/Delta) | Operational overhead unjustified at course scale | The MSDS 681 lakehouse next term (this design is meant to extend into it) |

## Likely Q&A
- *"Why a separate raw and staging tier?"* — raw is immutable provenance; staging (Silver) is the
  cleaned, conformed contract both stores consume. Splitting them is what lets a re-run be idempotent
  and what keeps the two stores in sync by construction.
- *"Why Parquet and JSONL, not CSV?"* — see [`file-formats.md`](file-formats.md).
