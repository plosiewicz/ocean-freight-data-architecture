# python-arango

**Layer:** the official ArangoDB Python driver — the idempotent graph loader and AQL executor.

## What it does
python-arango (8.x) is ArangoDB's official Python driver: create collections/indexes/graphs, run
AQL, and execute idempotent `UPSERT` loads. It's how the pipeline talks to the graph from Python.

## Role in our project
- `lib/arango_client.py` (env-cred, TLS-on connection) + `lib/graph_loader.py`: create-if-absent the
  5 vertex + 4 edge collections, the named graph, and the chokepoint vertex-centric index; then
  **idempotently `UPSERT`** every vertex/edge keyed on its deterministic `_key`.
- The single `load_graph()` entrypoint is called from **both** the Airflow `load_arango` task and the
  `make load-arango` target — one loader, two callers.
- Runs the UC3/UC4 AQL (`lib/graph_queries.py`) with **bind variables only** (no string interpolation).

## Why it's the best option here
- **Official driver, current API** — 8.x targets the ArangoDB 3.12 HTTP API our cluster runs; first-class
  support for collections, named graphs, indexes, and AQL.
- **Idempotent `UPSERT { _key } INSERT … UPDATE …`** is exactly the load pattern we need: a re-run
  leaves the graph byte-stable, never duplicating or corrupting it (we explicitly forbid
  wipe-then-reload).
- **Bind-variable AQL** keeps the loaders injection-safe and lets the same pure row-builders be
  unit-tested offline (no cluster needed).

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| `arangoimport` (bulk CLI) | Great for bulk files, but we need orchestrated, conditional, *idempotent* loads from Python; kept as an optional bulk path | One-shot bulk vertex/edge file loads |
| Raw HTTP calls to the Arango API | Reinventing the driver; loses connection/retry/typing niceties | Never, when the official driver exists |
| Spark/Datastore connectors | Big-data ingest machinery, unjustified at ≤100K edges | True large-scale graph ingest |
| `arangoimp` (old alias) | Deprecated | Never |

## Likely Q&A
- *"How are loads idempotent?"* — every write is `UPSERT` keyed on a deterministic `_key`
  (UN/LOCODE / IMO / SCAC / `origin__dest`); re-running the DAG leaves identical bytes. Wipe-then-reload
  is explicitly forbidden (it caused a load race earlier in the project).
- *"How do the two stores stay joined?"* — the driver writes `_key`s identical to the BigQuery business
  keys, so a graph result lines up 1:1 with a warehouse row.
