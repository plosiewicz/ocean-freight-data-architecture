# Landing formats — Parquet + JSONL

**Layer:** the on-disk formats in the GCS Bronze/Silver tiers. (Not a "tool," but the grader may ask.)

## What they are
- **Parquet** — columnar, compressed, schema-embedded tabular format.
- **JSONL** (newline-delimited JSON) — one JSON object per line; schema-flexible.

## Role in our project
- **Parquet** for the tabular sources and conformed tables: AIS, port/vessel/carrier reference,
  trade-flow priors, and all `dim_*` / `fact_*` Silver tables.
- **JSONL** for the synthetic event streams (schedules, bookings, container events) whose schema is
  ours and may evolve, and which carry nested/JSON-typed fields.

## Why these are the best options here
- **Parquet** is the recommended BigQuery load format: columnar means best scan economics, compression
  shrinks storage, and the embedded schema gives clean, explicit type mapping into the star.
- **JSONL** is the safe default for evolving, nested event records — JSON-typed columns can't round-trip
  through a Parquet load, so forcing events into Parquet would lose fidelity. JSONL loads into BigQuery
  as `NEWLINE_DELIMITED_JSON` directly.
- Splitting by data shape (columnar for stable tabular, JSONL for evolving events) is the
  BigQuery-idiomatic choice and avoids fighting either format.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| CSV everywhere | No schema embedding, weak typing, slow parse, no compression | A raw source that *arrives* as CSV — we convert it to Parquet at staging |
| Parquet for events too | JSON-typed/nested event columns can't round-trip through a Parquet load | Events with a fixed, flat, stable schema |
| Avro / ORC | Fine columnar/row options, but Parquet is the BQ-recommended, pyarrow-native one | Avro for streaming/Kafka pipelines |
| A table format (Iceberg/Delta) | Adds catalog/operational overhead beyond course scope | The MSDS 681 lakehouse |

## Likely Q&A
- *"Why two formats?"* — match the format to the data: columnar Parquet for stable tabular (cheap
  scans, clean BQ types), JSONL for evolving nested events (no lossy Parquet round-trip).
- *"What about CSV sources?"* — some real extracts arrive as CSV; we convert them to Parquet at the
  staging step rather than loading CSV into BigQuery.
