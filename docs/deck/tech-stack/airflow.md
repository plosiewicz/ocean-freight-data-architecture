# Apache Airflow 3.0 (orchestration — now bonus)

**Layer:** orchestration — the `ofa_warehouse` DAG. *Per the final brief, orchestration is bonus; we
built it, so it counts toward bonus rather than being the spine of the talk.*

## What it does
Airflow is the de-facto Python workflow orchestrator: DAGs of tasks with dependencies, retries,
scheduling, and operators for external systems. We run **Airflow 3.0** (Task SDK decorators), with
the Google provider operators for the BigQuery load leg.

## Role in our project
- One DAG, `dags/ofa_warehouse_dag.py`:
  `stage_conform` (build Silver) → **parallel** `load_bigquery` ∥ `load_arango` →
  **fan-in `verify`** (row counts + cross-store reconcile + live UC3/UC4 anti-degeneracy).
- `verify` depends on **both** load legs, so a half-loaded store can't pass the gate by accident —
  it enforces the "one transform, two sinks" contract at runtime.
- **Plain Apache Airflow, Composer-portable:** standard operators only; runs locally via
  `airflow dags test ofa_warehouse 2024-01-31` and lifts onto **Cloud Composer 3** unchanged.
  `tests/test_dag.py` guards portability (asserts no managed-runtime-specific import).

## Why it's the best option here
- **It's the rubric's named orchestration layer** — Airflow DAGs are exactly the expected pattern,
  and the course originally required *managed* Airflow (Cloud Composer 3).
- **Plain-Airflow-but-Composer-portable** is the cost-smart move: we get a real, runnable DAG and the
  cloud-ETL requirement (the GCS→BQ load jobs) without paying for an always-on Composer environment
  during development. It promotes to CC3 with no code change.
- **Parallel-leg + fan-in modeling** is precisely what a DAG expresses well and a shell script does not.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| Cloud Composer 3 (managed Airflow) | The target runtime — but an always-on env is the real cost driver; we stay portable and run plain Airflow until needed | Production / when managed Airflow is required to be running |
| A Makefile / shell script | We *do* have `make` targets, but they don't model parallel legs + a fan-in gate, retries, or scheduling | Simple linear local runs |
| Dagster / Prefect | Capable orchestrators, but Airflow is the rubric's expected tool and the GCP-native one | Asset-centric or Python-first orchestration outside GCP |
| Cloud Composer 1 / 2 | On the EOL path (Sep 15 2026); CC1 creation already disabled | Never for new work |
| Airflow 3.1 | Still preview — risky for a graded deliverable | After GA |

## Likely Q&A
- *"Managed or self-hosted Airflow?"* — plain Apache Airflow 3.0, deliberately Composer-portable. The
  cloud-ETL requirement is met by the GCS→BigQuery load jobs themselves; we avoid an always-on
  Composer bill while keeping a one-line path to CC3.
- *"Why is `verify` downstream of both loads?"* — cross-store reconciliation can only run once both
  stores are populated; fanning in there is what makes the two-sink consistency check meaningful.
