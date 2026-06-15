"""Offline DagBag + Composer-portability guards for ofa_warehouse_dag (ETL-03).

Network-free structure tests (no scheduler, no live GCS/BQ) — mirrors the
determinism-test style of tests/test_generators.py. They assert:

  * the DAG imports with ZERO import errors and exposes dag_id == "ofa_warehouse";
  * the expected task ids are present (stage_conform -> loads -> merges/overwrites
    -> verify);
  * the dependency edges are correct (stage_conform upstream of every load; verify
    last; each SCD2 MERGE downstream of its staging load);
  * `schedule is None` (manual / `airflow dags test` only — bounded course slice);
  * the D-01a portability guard: the DAG source imports NOTHING matching `composer`
    / Composer-environment APIs, and uses the non-deprecated BigQueryInsertJobOperator
    (not BigQueryExecuteQueryOperator).

The LIVE end-to-end run is the human-verify checkpoint in 05-03-PLAN.md, not a unit test.
"""

from __future__ import annotations

import os
import pathlib
import re

import pytest

DAGS_DIR = pathlib.Path(__file__).resolve().parent.parent / "dags"
DAG_FILE = DAGS_DIR / "ofa_warehouse_dag.py"
DAG_ID = "ofa_warehouse"

EXPECTED_TASKS = {
    "stage_conform",
    "load_staging_dim_vessel",
    "load_staging_dim_carrier",
    "merge_dim_vessel",
    "merge_dim_carrier",
    "overwrite_dim_vessel",
    "overwrite_dim_carrier",
    "overwrite_dim_port",
    "overwrite_dim_lane",
    "overwrite_operated_by",
    "overwrite_fact_voyage_leg",
    "overwrite_fact_port_call",
    "verify",
}


@pytest.fixture(scope="module")
def dag():
    """Load ofa_warehouse via DagBag (offline). AIRFLOW_HOME isolated to a tmp dir."""
    os.environ.setdefault("AIRFLOW_HOME", "/tmp/ofa_airflow_test_home")
    from airflow.models.dagbag import DagBag

    db = DagBag(str(DAGS_DIR), include_examples=False)
    assert not db.import_errors, f"DAG import errors: {db.import_errors}"
    assert DAG_ID in db.dags, f"{DAG_ID} not found; have {list(db.dags)}"
    return db.dags[DAG_ID]


def test_dag_imports_without_errors(dag) -> None:
    assert dag.dag_id == DAG_ID


def test_expected_task_set(dag) -> None:
    actual = {t.task_id for t in dag.tasks}
    assert actual == EXPECTED_TASKS, (
        f"task set mismatch:\n missing={EXPECTED_TASKS - actual}\n"
        f" extra={actual - EXPECTED_TASKS}"
    )


def test_schedule_is_none(dag) -> None:
    """Manual-only DAG: no recurring schedule (bounded course slice)."""
    assert dag.schedule is None, f"expected schedule None, got {dag.schedule!r}"


def test_stage_conform_upstream_of_every_load(dag) -> None:
    sc = dag.get_task("stage_conform")
    loads = {t for t in EXPECTED_TASKS if t.startswith(("load_staging_", "overwrite_"))}
    assert loads <= set(sc.downstream_task_ids), (
        f"stage_conform must precede every load; missing="
        f"{loads - set(sc.downstream_task_ids)}"
    )


def test_verify_is_terminal_and_downstream_of_loads(dag) -> None:
    v = dag.get_task("verify")
    assert not v.downstream_task_ids, "verify must be the terminal task"
    # verify must be downstream of the fact overwrites + the merges.
    must_precede_verify = {
        "overwrite_fact_voyage_leg",
        "overwrite_fact_port_call",
        "merge_dim_vessel",
        "merge_dim_carrier",
    }
    assert must_precede_verify <= set(v.upstream_task_ids), (
        f"verify must run after {must_precede_verify}; missing="
        f"{must_precede_verify - set(v.upstream_task_ids)}"
    )


def test_each_merge_downstream_of_its_staging_load(dag) -> None:
    for dim in ("dim_vessel", "dim_carrier"):
        merge = dag.get_task(f"merge_{dim}")
        assert f"load_staging_{dim}" in merge.upstream_task_ids, (
            f"merge_{dim} must run after load_staging_{dim}"
        )


def test_no_composer_import_guard(dag) -> None:
    """D-01a: the DAG source must import NOTHING Composer-specific (plain Airflow)."""
    src = DAG_FILE.read_text(encoding="utf-8")
    # Only inspect import lines so prose/docstring mentions don't false-positive.
    import_lines = [
        ln for ln in src.splitlines()
        if re.match(r"\s*(from|import)\s", ln)
    ]
    joined = "\n".join(import_lines).lower()
    assert "composer" not in joined, (
        f"Composer-specific import found (D-01a violation): {import_lines}"
    )
    assert "cloudcomposer" not in joined.replace(" ", "")


def test_uses_non_deprecated_operator(dag) -> None:
    """Uses BigQueryInsertJobOperator, never the deprecated ExecuteQueryOperator."""
    src = DAG_FILE.read_text(encoding="utf-8")
    assert "BigQueryInsertJobOperator" in src
    assert "BigQueryExecuteQueryOperator" not in src


def test_stage_conform_reuses_land_silver(dag) -> None:
    """stage_conform reuses the Phase-4 transform (D-03), not a rewrite."""
    src = DAG_FILE.read_text(encoding="utf-8")
    assert "land_silver" in src, "stage_conform must reuse silver.land_silver (D-03)"
