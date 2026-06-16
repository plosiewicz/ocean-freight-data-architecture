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
      - SCD2 dims (dim_vessel/dim_carrier) load EXCLUSIVELY via staging -> MERGE
        (CR-02/CR-03 fix): load_staging_dim_* WRITE_TRUNCATEs the authoritative Silver
        SCD2 snapshot into stg_dim_* , then merge_dim_* (sql/merge_dim_*.sql) upserts
        staging -> the persistent dim. The prior WRITE_TRUNCATE-of-dim "overwrite_dim_*"
        tasks were REMOVED: they raced the MERGE on the same table (CR-03, no ordering
        edge) and made the MERGE a structural no-op against its own overwritten output
        (CR-02). With only the MERGE writing the dim, the MERGE is the genuine,
        idempotent, SCD2-demonstrating load (D-04 named MERGE pattern).
      - SCD1 dims (dim_port/dim_lane) + the operated_by bridge load via WRITE_TRUNCATE
        of the authoritative Silver snapshot -> the live, robustly-idempotent bulk path.
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
import sys

# --------------------------------------------------------------------------- #
# Repo-root sys.path bootstrap (PARSE-TIME, runs in BOTH the parse and the task
# subprocess re-import). Airflow's `dags test` (and the scheduler) execute each
# task in a SUBPROCESS that re-imports this DAG module but whose sys.path does
# NOT include the project repo root — so `from silver import land_silver` inside
# a task callable would raise ModuleNotFoundError despite an offline DagBag PARSE
# passing (parse from the repo cwd ≠ execute in a subprocess). Inserting the repo
# root (the dags/ parent) here, at module top, makes the project packages
# (silver/, lib/, ingest/, data_gen/, scripts/) importable in ANY runtime with
# ZERO install step. Portable: no editable install, no Composer-specific API —
# on Composer the project code ships alongside the DAG under the same parent, so
# the same bootstrap holds. tests/test_dag.py guards this (closes parse-vs-execute).
# --------------------------------------------------------------------------- #
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from airflow.providers.google.cloud.operators.bigquery import (  # noqa: E402
    BigQueryInsertJobOperator,
)
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import (  # noqa: E402
    GCSToBigQueryOperator,
)
from airflow.sdk import dag, task  # noqa: E402

# --------------------------------------------------------------------------- #
# Constants (no managed-runtime config; plain Airflow + Google provider only).
# --------------------------------------------------------------------------- #
PROJECT = "data-architecture-msds683"
DATASET = "ofa_star"
BUCKET = "data-architecture-msds683-bronze"
LOCATION = "US"  # match the US Bronze/Silver bucket + ofa_star dataset (D-04a).

_SQL_DIR = _REPO_ROOT / "sql"


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
    def load_arango(bucket: str = BUCKET) -> str:
        """Sink #2 off the SAME stage_conform output — the ETL-05 'one transform,
        two sinks' proof (D-05). Runs PARALLEL to the BQ loads, reading the identical
        landed silver/ Parquet, and idempotently UPSERTs the conformed dims + the
        synthetic lane network into the managed ocean_network graph over HTTPS by
        deterministic _key (UN/LOCODE/IMO/SCAC, D-11). Connects ONLY via
        lib.arango_client (env creds, TLS-on) inside graph_loader.load_graph.

        The `from lib import graph_loader` import is INSIDE the task body (matching
        stage_conform's in-task `from silver import land_silver`) so the offline
        DagBag parse imports NO cluster/managed-runtime module — tests/test_dag.py
        guards this. graph_loader, in turn, imports lib.arango_client lazily inside
        load_graph, so even importing graph_loader at parse time stays creds-free.
        """
        from lib import graph_loader

        summary = graph_loader.load_graph(bucket=bucket)
        print(f"[INFO] load_arango complete (ETL-05 sink #2): {summary}")
        return bucket

    @task
    def verify(bucket: str) -> None:
        """Assert the served facts populated AND the UC use cases are non-degenerate.

        Two checks, both run only after BOTH sinks load (this task fans in on the BQ
        loads AND load_arango — the Pitfall-5 guard):

          1. Network-light BQ sanity: fact_voyage_leg row count > 0 (ETL-02).
          2. UC non-degeneracy (06-07): invoke scripts.verify.gate_uc_anti_degeneracy,
             which EXECUTES UC3 reroute-impact (SUEZ/PANAMA detour delta>0) + the
             GIBRALTAR genuine-unreachability drop + the UC4 weighted reroute (delta>0)
             against the managed ocean_network graph. This makes the green-but-hollow
             failure impossible to ship via the pipeline too — a degenerate UC fails
             the DAG here, not silently in a green gate. The import is INSIDE the task
             body so the offline DagBag parse pulls in NO cluster module (mirrors
             stage_conform / load_arango; tests/test_dag.py guards this).

        The formal full idempotency ladder (re-run row-count stable, exit 12) lives in
        scripts/verify.py `make verify`; here we wire the fact gate + the UC gate so
        the pipeline cannot declare success while a UC is degenerate.
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

        # UC non-degeneracy gate (06-07) — the pipeline's recurrence guard. Connects
        # to the managed cluster via the analytics facades' lazy get_db (env creds,
        # TLS-on); prints only [CITE] counts, never credentials (T-06-01).
        from scripts.verify import gate_uc_anti_degeneracy

        if not gate_uc_anti_degeneracy():
            raise AssertionError(
                "verify: UC anti-degeneracy gate FAILED — UC3 reroute-impact / "
                "GIBRALTAR fragmentation / UC4 reroute is degenerate (the green-but-"
                "hollow failure). See [FAIL] hints above."
            )
        print("[INFO] verify: UC anti-degeneracy gate passed (UC3/UC4 non-degenerate, GRAPH-02/03).")

    # --- Topology: stage_conform >> loads >> (merges + overwrites) >> verify -----
    staged = stage_conform()

    # Staging loads for the two SCD2 dims (the MERGE source tables).
    stg_vessel = _load_staging("dim_vessel")
    stg_carrier = _load_staging("dim_carrier")

    # SCD2 MERGE against the freshly loaded staging tables (demo/idempotency, D-04).
    merge_vessel = _merge_dim("dim_vessel")
    merge_carrier = _merge_dim("dim_carrier")

    # Authoritative overwrite loads (the LIVE idempotent bulk path). NOTE (CR-03):
    # the SCD2 dims (dim_vessel/dim_carrier) are DELIBERATELY ABSENT here — they are
    # loaded EXCLUSIVELY via staging -> MERGE (stg_* >> merge_*). The prior
    # overwrite_dim_vessel/overwrite_dim_carrier WRITE_TRUNCATE tasks were removed:
    # they raced the MERGE on the same table and made the MERGE a no-op (CR-02/CR-03).
    #   - SCD1 dims + operated_by bridge: WRITE_TRUNCATE snapshot
    #   - facts: WRITE_TRUNCATE per dt= partition
    ow_port = _overwrite_dim("dim_port")
    ow_lane = _overwrite_dim("dim_lane")
    ow_operated_by = _overwrite_dim("operated_by")
    ow_voyage_leg = _overwrite_fact("fact_voyage_leg")
    ow_port_call = _overwrite_fact("fact_port_call")

    # Sink #2: the ArangoDB load, PARALLEL to the BQ loads off the SAME staging
    # (ETL-05 "one transform, two sinks", D-05). It is NOT a BQ operator — it is the
    # graph projection — so it sits beside the BQ loads, not after them.
    arango = load_arango(staged)

    final = verify(staged)

    # stage_conform precedes every load — BOTH sinks (BQ loads AND the Arango load).
    staged >> [
        stg_vessel,
        stg_carrier,
        ow_port,
        ow_lane,
        ow_operated_by,
        ow_voyage_leg,
        ow_port_call,
        arango,
    ]

    # SCD2 dims load via staging -> MERGE ONLY (the MERGE is the sole writer of the
    # persistent dim, so there is no shared-table race; CR-02/CR-03 fix).
    stg_vessel >> merge_vessel
    stg_carrier >> merge_carrier

    # verify runs last — after every load + merge AND the Arango load. Fanning in on
    # BOTH sinks is the Pitfall-5 guard: the cross-store reconciliation gates inside
    # scripts/verify.py (exit 16..18) must only run once BQ AND ArangoDB are both
    # populated, so a half-loaded store cannot false-pass/false-fail the check (D-05).
    [
        ow_port,
        ow_lane,
        ow_operated_by,
        ow_voyage_leg,
        ow_port_call,
        merge_vessel,
        merge_carrier,
        arango,
    ] >> final


ofa_warehouse()
