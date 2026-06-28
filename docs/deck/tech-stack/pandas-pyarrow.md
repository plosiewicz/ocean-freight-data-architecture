# pandas + pyarrow

**Layer:** tabular shaping (pandas) and the Parquet read/write + BQ-compatible typing engine (pyarrow).

## What it does
- **pandas** — in-memory DataFrames for shaping dimension and fact frames before they're written,
  and for light transforms in the generators.
- **pyarrow** — the columnar engine behind `pandas.to_parquet`/`read_parquet`; writes the partitioned
  Parquet we land in GCS and maps cleanly to BigQuery's load types.

## Role in our project
- Build `dim_*` / `fact_*` frames in `silver/` and shape generator output in `data_gen/`.
- Write partitioned **Parquet** to the GCS Bronze/Silver tiers and read it back in `scripts/verify.py`
  and `lib/graph_loader.py` (`pyarrow.parquet`).
- pyarrow's type mapping is what makes the Parquet→BigQuery load clean (int64→INTEGER, float64→FLOAT,
  date→DATE, timestamp→TIMESTAMP) under explicit schemas.

## Why it's the best option here
- **pyarrow is the canonical Parquet engine** and the one BigQuery's loader expects — using it makes
  the columnar landing format and the warehouse load "just work" with clean types.
- **pandas is the least-friction tabular tool** for the dim/fact shaping at this scale; everyone on a
  data team reads it, and it's already a transitive dependency of the GCP/Arrow ecosystem.
- Together they keep the tabular path **columnar end to end** (Arrow in memory → Parquet on disk →
  columnar BQ), which is the scan-cost story.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| Polars | Faster, but pandas is sufficient at our volume and is the ecosystem default; no need for the swap | Large in-memory transforms where speed matters |
| Spark DataFrames | Cluster overhead unjustified at a bounded slice | Distributed big-data ETL |
| Raw `csv`/`json` + hand-rolled typing | Loses columnar compression, schema embedding, and clean BQ type mapping | One-off tiny files |
| fastparquet | pyarrow is the better-supported, BQ-aligned engine | Niche pandas-only setups |

## Likely Q&A
- *"Why Parquet via pyarrow rather than CSV?"* — columnar, compressed, schema-embedded, and it's the
  recommended BigQuery load format with clean type mapping. (More in [`file-formats.md`](file-formats.md).)
- *"Why pandas not Polars?"* — at our scale pandas is plenty and is the ecosystem default; Polars would
  be premature optimization.
