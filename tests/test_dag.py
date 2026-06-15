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
import subprocess
import sys
import textwrap

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
    # CR-02/CR-03: SCD2 dims load via staging->MERGE ONLY. The prior
    # overwrite_dim_vessel/overwrite_dim_carrier WRITE_TRUNCATE-of-dim tasks were
    # removed (they raced the MERGE on the same table + made it a no-op).
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


def test_dag_bootstraps_repo_root_on_sys_path(dag) -> None:
    """The DAG must insert the repo root onto sys.path AT PARSE TIME (source guard).

    Without this, Airflow `dags test` runs each task in a subprocess whose sys.path
    excludes the repo root, so `from silver import land_silver` inside the task
    callable raises ModuleNotFoundError even though the offline DagBag parse passed.
    """
    src = DAG_FILE.read_text(encoding="utf-8")
    assert "sys.path.insert" in src, (
        "DAG must bootstrap the repo root onto sys.path so task subprocesses can "
        "import project modules (silver/, lib/, ...) with no install step."
    )


def test_project_modules_importable_after_dag_load_in_clean_subprocess() -> None:
    """Closes the parse-vs-execute gap: in a CLEAN subprocess (repo root NOT on
    sys.path, cwd outside the repo), importing the DAG module must make `silver`
    and `land_silver` importable — proving the parse-time sys.path bootstrap fires
    exactly as it would inside an Airflow task subprocess. Fully offline.
    """
    script = textwrap.dedent(
        f"""
        import importlib.util
        import sys

        dag_file = {str(DAG_FILE)!r}
        repo_root = {str(DAGS_DIR.parent)!r}

        # Simulate the Airflow task subprocess: repo root absent from sys.path.
        sys.path[:] = [p for p in sys.path if p not in ("", ".", repo_root)]

        spec = importlib.util.spec_from_file_location("ofa_warehouse_dag", dag_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # If the bootstrap fired, these now resolve without any install / cwd help.
        from silver import land_silver  # noqa: F401
        print("OK")
        """
    )
    # Run from a directory OUTSIDE the repo so cwd cannot rescue the import.
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/tmp",
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0 and "OK" in proc.stdout, (
        "DAG load in a clean subprocess failed to make 'silver.land_silver' "
        f"importable (parse-vs-execute gap).\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
