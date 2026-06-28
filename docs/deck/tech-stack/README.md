# Tech Stack — per-tool justification

One file per tool in our stack. Each answers the brief's follow-up Q&A directly:
**what it does · its role in our project · why it's the best option here · alternatives considered.**

The diagram for slide F-8 is [`tech-stack-diagram.md`](tech-stack-diagram.md).

| Layer | Tool | File |
|---|---|---|
| Raw + staging | Google Cloud Storage | [`gcs.md`](gcs.md) |
| Landing formats | Parquet + JSONL | [`file-formats.md`](file-formats.md) |
| OLAP store | BigQuery | [`bigquery.md`](bigquery.md) |
| Graph store + analytics | ArangoDB (AQL / GAE) | [`arangodb.md`](arangodb.md) |
| Orchestration (bonus) | Apache Airflow 3.0 | [`airflow.md`](airflow.md) |
| Language / glue | Python 3.11 | [`python.md`](python.md) |
| Tabular shaping | pandas + pyarrow | [`pandas-pyarrow.md`](pandas-pyarrow.md) |
| Seeded randomness | NumPy | [`numpy.md`](numpy.md) |
| Synthetic identifiers | Faker | [`faker.md`](faker.md) |
| Graph driver/loader | python-arango | [`python-arango.md`](python-arango.md) |
| End product | Next.js + deck.gl + Vercel | [`nextjs-vercel.md`](nextjs-vercel.md) |
| Dev tooling | Make · pytest · Git/GitHub | [`dev-tooling.md`](dev-tooling.md) |

**The one-breath defense of the whole stack:** *managed-first* (GCS / BigQuery / managed ArangoDB /
Vercel — nothing to operate), *columnar-where-it's-OLAP and graph-where-it's-network* (the hybrid
thesis), and *deterministic everywhere* (seeded synthetic, idempotent loads, frozen goldens) so the
demo reproduces byte-for-byte.
