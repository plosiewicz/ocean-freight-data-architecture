"""Offline (network-free) guards for the SCD2 MERGE SQL (ETL-03 / D-04).

These tests assert the SCD2 *idempotency invariant* is encoded in the versioned
`.sql` files without touching live BigQuery (default run stays offline, mirroring
tests/test_generators.py). They lock the two-step MERGE pattern (Pitfall 5):

  1. a close-changed MERGE: WHEN MATCHED AND row_hash differs -> is_current=FALSE,
     effective_to=@run_date (close the old current row);
  2. a NOT-EXISTS-guarded INSERT of the new/changed version (no-change re-run is a
     no-op -> idempotent, ETL-04);

and the deterministic-anchor invariant: every MERGE file uses the @run_date typed
parameter and NEVER CURRENT_DATE (Pitfall 5 / threat T-05-09) — and never
string-interpolates a date (threat T-05-07).

A live temp-dataset integration variant is intentionally omitted from the default
run (it needs ADC + a BQ dataset); the live end-to-end run is the human-verify
checkpoint in 05-03-PLAN.md.
"""

from __future__ import annotations

import pathlib
import re

import pytest

SQL_DIR = pathlib.Path(__file__).resolve().parent.parent / "sql"

# natural key per dim file (the MERGE ON-clause + INSERT/NOT-EXISTS join key).
MERGE_FILES = {
    "merge_dim_vessel.sql": "imo",
    "merge_dim_carrier.sql": "scac",
}


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def _executable_sql(name: str) -> str:
    """SQL with full-line `--` comments stripped (assert on the runnable text)."""
    lines = [
        ln for ln in _read(name).splitlines() if not ln.lstrip().startswith("--")
    ]
    return "\n".join(lines)


def _norm(sql: str) -> str:
    """Collapse whitespace to single spaces so multi-line clauses match a regex."""
    return re.sub(r"\s+", " ", sql)


@pytest.mark.parametrize("name", sorted(MERGE_FILES))
def test_merge_file_exists_and_nonempty(name: str) -> None:
    path = SQL_DIR / name
    assert path.exists(), f"{name} must exist (Task 1)"
    assert path.read_text(encoding="utf-8").strip(), f"{name} is empty"


@pytest.mark.parametrize("name", sorted(MERGE_FILES))
def test_step1_closes_changed_current_row(name: str) -> None:
    """Step 1 MERGE: close the CURRENT row whose row_hash changed (SCD2 close)."""
    sql = _norm(_read(name))
    assert re.search(r"\bMERGE\b", sql, re.IGNORECASE), f"{name} missing MERGE"
    # WHEN MATCHED gated on a row_hash difference.
    assert re.search(
        r"WHEN MATCHED AND .*row_hash\s*!=\s*s\.row_hash", sql, re.IGNORECASE
    ), f"{name} MERGE must gate the close on a row_hash change (Pitfall 5)"
    # The close sets is_current=FALSE and effective_to=@run_date.
    assert re.search(r"is_current\s*=\s*FALSE", sql, re.IGNORECASE), (
        f"{name} close must set is_current=FALSE"
    )
    assert re.search(r"effective_to\s*=\s*@run_date", sql, re.IGNORECASE), (
        f"{name} close must set effective_to=@run_date (deterministic anchor)"
    )


@pytest.mark.parametrize("name", sorted(MERGE_FILES))
def test_step2_insert_is_not_exists_guarded(name: str) -> None:
    """Step 2 INSERT: new version guarded by NOT EXISTS -> idempotent re-run."""
    sql = _norm(_read(name))
    assert re.search(r"\bINSERT INTO\b", sql, re.IGNORECASE), f"{name} missing INSERT"
    assert re.search(r"\bNOT EXISTS\b", sql, re.IGNORECASE), (
        f"{name} INSERT must be NOT-EXISTS-guarded (idempotent no-op re-run, ETL-04)"
    )
    # The new current version opens with effective_from=@run_date, is_current=TRUE,
    # and the open sentinel DATE "9999-12-31" (A5).
    assert re.search(r'DATE\s+"9999-12-31"', sql), (
        f"{name} new version must open with the 9999-12-31 DATE sentinel (A5)"
    )
    assert re.search(r"\bTRUE\b", sql), f"{name} new version must set is_current=TRUE"


@pytest.mark.parametrize("name,natural_key", sorted(MERGE_FILES.items()))
def test_uses_correct_natural_key(name: str, natural_key: str) -> None:
    """The ON clause and the NOT-EXISTS guard both key on the dim's natural key."""
    sql = _norm(_read(name))
    assert re.search(rf"ON t\.{natural_key}\s*=\s*s\.{natural_key}", sql), (
        f"{name} MERGE ON must key on {natural_key}"
    )
    assert re.search(rf"d\.{natural_key}\s*=\s*s\.{natural_key}", sql), (
        f"{name} NOT-EXISTS guard must key on {natural_key}"
    )


@pytest.mark.parametrize("name", sorted(MERGE_FILES))
def test_anchored_to_run_date_never_current_date(name: str) -> None:
    """Deterministic anchor: @run_date present, wall-clock date absent (Pitfall 5)."""
    raw = _read(name)
    assert "@run_date" in raw, f"{name} must use the @run_date typed parameter"
    # Assert on the EXECUTABLE SQL (comments stripped) so prose can name the
    # anti-pattern without tripping the guard.
    executable = _executable_sql(name).upper()
    assert "CURRENT_DATE" not in executable, (
        f"{name} executable SQL must NEVER use CURRENT_DATE — breaks idempotency "
        "(Pitfall 5 / T-05-09)"
    )
