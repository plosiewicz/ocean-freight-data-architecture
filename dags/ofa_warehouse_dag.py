"""dags/ofa_warehouse_dag.py — the one warehouse DAG (ETL-02/ETL-03).

The single plain Apache Airflow 3.0 DAG that IS the implemented cloud-ETL slice:

    stage_conform -> load_staging_* -> (dim merges + dim/fact overwrites) -> verify

It runs the existing Phase-4 Silver transforms as a task callable (`stage_conform`
reuses `silver.land_silver.main(...)` verbatim — D-03, NO transform rewritten),
then loads the resulting `silver/` Parquet into the BigQuery star (`ofa_star`) via
the Google-provider operators, and asserts fact rows landed (`verify`).

DESIGN (defended):
  * PLAIN Apache Airflow 3.0, NOT a managed runtime (D-01). The cloud-ETL
    requirement is met independently by the GCS->BigQuery load jobs. The DAG stays
    fully PORTABLE (D-01a): only the Airflow 3.0 Task SDK (`from airflow.sdk
    import dag, task`) + the Google provider operators are imported — NOTHING
    runtime-specific. tests/test_dag.py guards this (asserts no managed-runtime import).
  * Task SDK decorators, not the legacy `airflow.models.DAG` path (RESEARCH Pattern 1).
  * `stage_conform` is SINK-AGNOSTIC: its output is the landed `silver/` Parquet.
    Phase 6 adds a parallel `load_arango` downstream of it from the SAME staging
    (the "one transform, two sinks" contract) — so this task must NOT couple to BQ.
  * Idempotent loads (ETL-04 / Pitfall 5):
      - dims load via WRITE_TRUNCATE of the AUTHORITATIVE Silver SCD2 snapshot
        (conform.py computes the SCD2 versioning deterministically) -> the live,
        robustly-idempotent bulk path (D-04 intent / RESEARCH Open Q3).
      - the SCD2 MERGE SQL (sql/merge_dim_*.sql) is ALSO wired as
        BigQueryInsertJobOperator tasks (the D-04-named MERGE, for the demo /
        idempotency narrative) running against staging tables loaded in the same DAG.
      - facts load via WRITE_TRUNCATE into the existing partitioned/clustered native
        tables (sql/ddl_star.sql) -> a re-run replaces the same dt= partitions with
        identical bytes (T-05-08). NEVER streaming inserts (Pitfall 6).
  * Explicit `schema_fields` (autodetect=False) so the Parquet load maps cleanly to
    the DDL types (Pitfall 3): int64->INTEGER, float64->FLOAT, date->DATE,
    timestamp->TIMESTAMP, string->STRING, bool->BOOLEAN.
  * @run_date passed to the MERGE as a TYPED DATE query parameter, never
    string-interpolated (threat T-05-07); deterministic job_id (Pitfall 1 / T-05-09).

Provenance: 05-03-PLAN.md Task 2; 05-RESEARCH.md § Pattern 1 / 2 / 3 + Code Examples
(GCSToBigQuery + BigQueryInsertJob + Local DAG run); 05-PATTERNS.md
§ dags/ofa_warehouse_dag.py; sql/ddl_star.sql (target schemas);
sql/merge_dim_{vessel,carrier}.sql (the SCD2 MERGE this DAG runs).

Local run (creds-backed, no scheduler):
    AIRFLOW__CORE__DAGS_FOLDER=$PWD/dags AIRFLOW_HOME=$PWD/.airflow \
        airflow dags test ofa_warehouse 2024-01-31
"""

from __future__ import annotations

import pathlib

from airflow.providers.google.cloud.operators.bigquery import (
    BigQueryInsertJobOperator,
)
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import (
    GCSToBigQueryOperator,
)
from airflow.sdk import dag, task

# --------------------------------------------------------------------------- #
# Constants (no managed-runtime config; plain Airflow + Google provider only).
# --------------------------------------------------------------------------- #
PROJECT = "data-architecture-msds683"
DATASET = "ofa_star"
BUCKET = "data-architecture-msds683-bronze"
LOCATION = "US"  # match the US Bronze/Silver bucket + ofa_star dataset (D-04a).

_SQL_DIR = pathlib.Path(__file__).resolve().parent.parent / "sql"


def _read_sql(name: str) -> str:
    """Read a versioned .sql file at DAG-parse time (the MERGE the operator runs)."""
    return (_SQL_DIR / name).read_text(encoding="utf-8")


def _qualified(table: str) -> str:
    return f"{PROJECT}.{DATASET}.{table}"


# --------------------------------------------------------------------------- #
# Explicit schema_fields per Silver entity (autodetect=False, Pitfall 3 / D-04).
# Column order/types mirror sql/ddl_star.sql exactly.
# --------------------------------------------------------------------------- #
SCHEMAS: dict[str, list[dict]] = {
    "fact_voyage_leg": [
        {"name": "vessel_imo", "type": "STRING", "mode": "NULLABLE"},
        {"name": "origin_unlocode", "type": "STRING", "mode": "NULLABLE"},
        {"name": "dest_unlocode", "type": "STRING", "mode": "NULLABLE"},
        {"name": "transit_hours", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "distance_nm", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "schedule_delta", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "dt", "type": "DATE", "mode": "NULLABLE"},
        {"name": "provenance", "type": "STRING", "mode": "NULLABLE"},
    ],
    "fact_port_call": [
        {"name": "vessel_imo", "type": "STRING", "mode": "NULLABLE"},
        {"name": "unlocode", "type": "STRING", "mode": "NULLABLE"},
        {"name": "arrival_ts", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "departure_ts", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "lat", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "lon", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "dt", "type": "DATE", "mode": "NULLABLE"},
        {"name": "provenance", "type": "STRING", "mode": "NULLABLE"},
    ],
    "dim_vessel": [
        {"name": "surrogate_key", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "imo", "type": "STRING", "mode": "NULLABLE"},
        {"name": "vessel_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "effective_from", "type": "DATE", "mode": "NULLABLE"},
        {"name": "effective_to", "type": "DATE", "mode": "NULLABLE"},
        {"name": "is_current", "type": "BOOLEAN", "mode": "NULLABLE"},
        {"name": "row_hash", "type": "STRING", "mode": "NULLABLE"},
        {"name": "provenance", "type": "STRING", "mode": "NULLABLE"},
    ],
    "dim_carrier": [
        {"name": "surrogate_key", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "scac", "type": "STRING", "mode": "NULLABLE"},
        {"name": "carrier_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "effective_from", "type": "DATE", "mode": "NULLABLE"},
        {"name": "effective_to", "type": "DATE", "mode": "NULLABLE"},
        {"name": "is_current", "type": "BOOLEAN", "mode": "NULLABLE"},
        {"name": "row_hash", "type": "STRING", "mode": "NULLABLE"},
        {"name": "provenance", "type": "STRING", "mode": "NULLABLE"},
    ],
    "dim_port": [
        {"name": "surrogate_key", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "unlocode", "type": "STRING", "mode": "NULLABLE"},
        {"name": "lat", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "lon", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "provenance", "type": "STRING", "mode": "NULLABLE"},
    ],
    "dim_lane": [
        {"name": "surrogate_key", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "lane_key", "type": "STRING", "mode": "NULLABLE"},
        {"name": "origin_unlocode", "type": "STRING", "mode": "NULLABLE"},
        {"name": "dest_unlocode", "type": "STRING", "mode": "NULLABLE"},
        {"name": "provenance", "type": "STRING", "mode": "NULLABLE"},
    ],
    "operated_by": [
        {"name": "vessel_imo", "type": "STRING", "mode": "NULLABLE"},
        {"name": "carrier_scac", "type": "STRING", "mode": "NULLABLE"},
        {"name": "provenance", "type": "STRING", "mode": "NULLABLE"},
    ],
}

# Silver GCS source-object globs (dims = snapshots no dt=; facts = dt= partitions).
SOURCE_OBJECTS: dict[str, list[str]] = {
    "fact_voyage_leg": ["silver/fact_voyage_leg/dt=*/fact_voyage_leg.parquet"],
    "fact_port_call": ["silver/fact_port_call/dt=*/fact_port_call.parquet"],
    "dim_vessel": ["silver/dim_vessel/dim_vessel.parquet"],
    "dim_carrier": ["silver/dim_carrier/dim_carrier.parquet"],
    "dim_port": ["silver/dim_port/dim_port.parquet"],
    "dim_lane": ["silver/dim_lane/dim_lane.parquet"],
    "operated_by": ["silver/operated_by/operated_by.parquet"],
}

# Fact partition/cluster spec (mirrors sql/ddl_star.sql).
FACT_PARTITION = {
    "fact_voyage_leg": ["origin_unlocode", "dest_unlocode", "vessel_imo"],
    "fact_port_call": ["unlocode", "vessel_imo"],
}


@dag(
    dag_id="ofa_warehouse",
    schedule=None,  # manual / `airflow dags test` only — bounded course slice.
    catchup=False,
    tags=["ofa", "warehouse"],
)
def ofa_warehouse():
    """stage_conform -> load_staging_* -> (merges + dim/fact overwrites) -> verify."""

    @task
    def stage_conform(bucket: str = BUCKET) -> str:
        """Reuse the Phase-4 Silver transform VERBATIM (D-03) — no rewrite here.

        Lands the conformed Silver (4 dims + operated_by snapshots, 2 facts under
        dt= partitions) idempotently via upload_if_absent. Sink-agnostic: its output
        is the landed silver/ Parquet (Phase 6 fans load_arango out from the same).
        """
        from silver import land_silver

        rc = land_silver.main(["--bucket", bucket, "--step", "all"])
        if rc != 0:
            raise RuntimeError(f"stage_conform: land_silver returned {rc}")
        return bucket

    # --- Load each Silver entity into a BQ staging table (WRITE_TRUNCATE) --------
    def _load_staging(name: str) -> GCSToBigQueryOperator:
        return GCSToBigQueryOperator(
            task_id=f"load_staging_{name}",
            bucket=BUCKET,
            source_objects=SOURCE_OBJECTS[name],
            destination_project_dataset_table=_qualified(f"stg_{name}"),
            source_format="PARQUET",
            write_disposition="WRITE_TRUNCATE",
            create_disposition="CREATE_IF_NEEDED",
            autodetect=False,
            schema_fields=SCHEMAS[name],
            location=LOCATION,
        )

    # --- Overwrite the served fact tables per dt= partition (idempotent) --------
    def _overwrite_fact(name: str) -> GCSToBigQueryOperator:
        return GCSToBigQueryOperator(
            task_id=f"overwrite_{name}",
            bucket=BUCKET,
            source_objects=SOURCE_OBJECTS[name],
            destination_project_dataset_table=_qualified(name),
            source_format="PARQUET",
            write_disposition="WRITE_TRUNCATE",  # idempotent per-partition overwrite
            create_disposition="CREATE_IF_NEEDED",
            autodetect=False,
            schema_fields=SCHEMAS[name],
            time_partitioning={"type": "DAY", "field": "dt"},
            cluster_fields=FACT_PARTITION[name],
            location=LOCATION,
        )

    # --- Overwrite a dim/bridge as the authoritative Silver snapshot (D-04) -----
    def _overwrite_dim(name: str) -> GCSToBigQueryOperator:
        return GCSToBigQueryOperator(
            task_id=f"overwrite_{name}",
            bucket=BUCKET,
            source_objects=SOURCE_OBJECTS[name],
            destination_project_dataset_table=_qualified(name),
            source_format="PARQUET",
            write_disposition="WRITE_TRUNCATE",
            create_disposition="CREATE_IF_NEEDED",
            autodetect=False,
            schema_fields=SCHEMAS[name],
            location=LOCATION,
        )

    # --- SCD2 MERGE (the D-04-named demo/idempotency artifact) -------------------
    def _merge_dim(name: str) -> BigQueryInsertJobOperator:
        return BigQueryInsertJobOperator(
            task_id=f"merge_{name}",
            configuration={
                "query": {
                    "query": _read_sql(f"merge_{name}.sql"),
                    "useLegacySql": False,
                    "queryParameters": [
                        {
                            "name": "run_date",
                            "parameterType": {"type": "DATE"},
                            "parameterValue": {"value": "{{ ds }}"},
                        },
                    ],
                }
            },
            location=LOCATION,
            job_id=f"merge_{name}_{{{{ ds_nodash }}}}",  # deterministic (Pitfall 1)
        )

    @task
    def verify(bucket: str) -> None:
        """Assert the served facts populated (the gate detail lands in 05-04).

        Network-light sanity: query fact_voyage_leg row count via the BQ client and
        fail loud if zero. The formal idempotency gate (re-run row-count stable) is
        scripts/verify.py in Plan 04; here we wire the task + edge and assert > 0.
        """
        from google.cloud import bigquery

        client = bigquery.Client(project=PROJECT, location=LOCATION)
        n = list(
            client.query(
                f"SELECT COUNT(*) AS n FROM `{_qualified('fact_voyage_leg')}`"
            ).result()
        )[0]["n"]
        if n <= 0:
            raise AssertionError(
                f"verify: fact_voyage_leg has {n} rows (expected > 0) — load failed."
            )
        print(f"[INFO] verify: fact_voyage_leg has {n} rows (> 0, ETL-02 satisfied).")

    # --- Topology: stage_conform >> loads >> (merges + overwrites) >> verify -----
    staged = stage_conform()

    # Staging loads for the two SCD2 dims (the MERGE source tables).
    stg_vessel = _load_staging("dim_vessel")
    stg_carrier = _load_staging("dim_carrier")

    # SCD2 MERGE against the freshly loaded staging tables (demo/idempotency, D-04).
    merge_vessel = _merge_dim("dim_vessel")
    merge_carrier = _merge_dim("dim_carrier")

    # Authoritative overwrite loads (the LIVE idempotent bulk path):
    #   - SCD2 dims: WRITE_TRUNCATE the Silver SCD2 snapshot (D-04 / Open Q3)
    #   - SCD1 dims + operated_by bridge: truncate-insert snapshot
    #   - facts: WRITE_TRUNCATE per dt= partition
    ow_vessel = _overwrite_dim("dim_vessel")
    ow_carrier = _overwrite_dim("dim_carrier")
    ow_port = _overwrite_dim("dim_port")
    ow_lane = _overwrite_dim("dim_lane")
    ow_operated_by = _overwrite_dim("operated_by")
    ow_voyage_leg = _overwrite_fact("fact_voyage_leg")
    ow_port_call = _overwrite_fact("fact_port_call")

    final = verify(staged)

    # stage_conform precedes every load.
    staged >> [
        stg_vessel,
        stg_carrier,
        ow_vessel,
        ow_carrier,
        ow_port,
        ow_lane,
        ow_operated_by,
        ow_voyage_leg,
        ow_port_call,
    ]

    # Each SCD2 MERGE runs after its staging table is loaded (demo artifact).
    stg_vessel >> merge_vessel
    stg_carrier >> merge_carrier

    # verify runs last — after every load + merge.
    [
        ow_vessel,
        ow_carrier,
        ow_port,
        ow_lane,
        ow_operated_by,
        ow_voyage_leg,
        ow_port_call,
        merge_vessel,
        merge_carrier,
    ] >> final


ofa_warehouse()
