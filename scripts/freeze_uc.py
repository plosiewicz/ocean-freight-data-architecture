"""scripts/freeze_uc.py — freeze all FOUR use-case answers to committable goldens.

The Phase-7 (DEL-01) demo-safety FREEZER. Extends the ``scripts/freeze_criticality.py``
contract — read live state -> VALIDATE all rows populated (WR-09: a partial/under-covered
read FAILS, never silently freezes a degenerate golden) -> SORT for byte-determinism
(Pitfall 3: cluster/BQ row order is arbitrary) -> reuse the prior ``frozen_at_iso`` on an
unchanged body (WR-06 byte-identity) -> write a single-line, sorted, CREDENTIAL-FREE
payload — ONCE PER UC into ``data/golden/uc{1,2,3,4}.golden.json``.

  UC1 (``sql/uc1_eta_reliability.sql``) -> BigQuery ADC read (mirror verify._bq_client /
       gate_uc1_nonnull), rows -> sorted plain dicts.
  UC2 (``sql/uc2_dwell_trend.sql``)    -> same BigQuery pattern (mirror gate_uc2_trend).
  UC3 (``analytics/snapshot_uc.snapshot_uc3``) -> transit-share + SUEZ reroute-impact +
       GIBRALTAR open-vs-closed reachable counts (the non-degeneracy proof).
  UC4 (``analytics/snapshot_uc.snapshot_uc4``) -> baseline vs SUEZ-disabled reroute path.

Credential safety (threats T-07-01 / T-07-03 / T-06-08): BigQuery via
``bigquery.Client(project=BQ_PROJECT)`` ADC only (no key file); Arango via the snapshot
runners' ``lib.arango_client.get_db`` delegation only. The goldens carry ONLY
counts/floats/strings/lists — zero credentials. Prints labels + counts only, never a
password/JWT/connection string.

Versioned-query discipline (threat T-07-02 / T-06-06): the UC1/UC2 SQL is read VERBATIM
from disk and run as-is; the UC3/UC4 runners pass every parameter as an AQL bind variable.

Non-degeneracy (success criterion): the frozen UC3 SUEZ reroute ``delta`` is strictly > 0
and the GIBRALTAR closed reachable total is strictly < the open baseline. The freezer
asserts DIRECTION ONLY — it never pins the exact 76.2h / 29->11 magnitudes, which are
coupled to live cluster state.

The goldens are made git-trackable via a ``.gitignore`` per-component re-include block
(``data/*`` + ``!data/golden/`` + ``data/golden/*`` + ``!data/golden/*.golden.json``): a
negation alone CANNOT re-include a file under an excluded directory, so each path
component is re-included in order.

Provenance: scripts/freeze_criticality.py (the canonical freeze contract analog).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
GOLDEN_DIR: Path = REPO_ROOT / "data" / "golden"

UC1_SQL: Path = REPO_ROOT / "sql" / "uc1_eta_reliability.sql"
UC2_SQL: Path = REPO_ROOT / "sql" / "uc2_dwell_trend.sql"

BQ_PROJECT: str = "data-architecture-msds683"

EXIT_OK: int = 0
EXIT_FAIL: int = 1
EXIT_EMPTY: int = 2  # a UC produced zero rows / an under-covered read (never overwrite)
EXIT_CLUSTER_UNREACHABLE: int = 3

UC_NAMES: tuple[str, ...] = ("uc1", "uc2", "uc3", "uc4")


def _ok(label: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"[OK] {label}{suffix}")


def _fail(label: str, hint: str) -> None:
    print(f"[FAIL] {label}", file=sys.stderr)
    print(f"  hint: {hint}", file=sys.stderr)


def _info(label: str) -> None:
    print(f"[INFO] {label}")


def _golden_path(uc: str) -> Path:
    return GOLDEN_DIR / f"{uc}.golden.json"


def _resolve_frozen_at_iso(golden_path: Path, new_body: dict) -> str:
    """Reuse the prior frozen_at_iso when the body (minus the timestamp) is unchanged,
    so re-freezes against stable state are byte-identical (WR-06). Parameterized per
    golden path — VERBATIM analog of freeze_criticality._resolve_frozen_at_iso."""
    if golden_path.exists():
        try:
            prior = json.loads(golden_path.read_text())
        except (OSError, json.JSONDecodeError):
            prior = None
        if isinstance(prior, dict):
            prior_ts = prior.get("frozen_at_iso")
            prior_body = {k: v for k, v in prior.items() if k != "frozen_at_iso"}
            if isinstance(prior_ts, str) and prior_body == new_body:
                return prior_ts
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _round_floats(obj: Any) -> Any:
    """Recursively round every float to 12 places for byte-stability (Pitfall 3)."""
    if isinstance(obj, float):
        return round(float(obj), 12)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    return obj


def _write_golden(uc: str, body: dict) -> None:
    """Reuse-timestamp + single-line + sorted-keys write (the byte-stable contract)."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    body = _round_floats(body)
    path = _golden_path(uc)
    row = {"frozen_at_iso": _resolve_frozen_at_iso(path, body), **body}
    path.write_text(json.dumps(row, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- #
# UC1 / UC2 — BigQuery ADC reads (mirror verify._bq_client / gate_uc1/2)         #
# --------------------------------------------------------------------------- #
def _bq_client():
    """ADC-only BigQuery client (mirror verify._bq_client; no key file, T-07-03)."""
    from google.cloud import bigquery

    return bigquery.Client(project=BQ_PROJECT)


def _bq_rows(sql_path: Path) -> list[dict[str, Any]]:
    """Run a versioned SQL file VERBATIM and return rows as plain dicts."""
    client = _bq_client()
    sql = sql_path.read_text(encoding="utf-8")
    rows = list(client.query(sql).result())
    out: list[dict[str, Any]] = []
    for r in rows:
        d: dict[str, Any] = {}
        for k in r.keys():
            v = r[k]
            if isinstance(v, datetime.date):
                d[k] = v.isoformat()
            elif isinstance(v, float):
                d[k] = round(float(v), 12)
            elif isinstance(v, (int, str)) or v is None:
                d[k] = v
            else:
                d[k] = str(v)
        out.append(d)
    return out


def _freeze_uc1() -> tuple[int, dict | None]:
    if not UC1_SQL.exists():
        _fail("uc1: SQL missing", f"expected {UC1_SQL}")
        return EXIT_FAIL, None
    rows = _bq_rows(UC1_SQL)
    if not rows:
        _fail("uc1: BigQuery returned zero rows", "run `make load-bq` then re-freeze (WR-09)")
        return EXIT_EMPTY, None
    # WR-09: the UC1 answer is non-degenerate only if >=1 row carries a real delay.
    nonnull = [r for r in rows if r.get("avg_delay_hours") is not None]
    if not nonnull:
        _fail("uc1: no row with non-NULL avg_delay_hours", "schedule_delta dead for this slice (WH-02)")
        return EXIT_EMPTY, None
    rows.sort(key=lambda r: (str(r.get("carrier_scac") or ""), str(r.get("lane_key") or ""),
                             -(r.get("legs") or 0)))
    body = {"use_case": "UC1", "store": "bigquery", "query": "sql/uc1_eta_reliability.sql",
            "row_count": len(rows), "rows": rows}
    return EXIT_OK, body


def _freeze_uc2() -> tuple[int, dict | None]:
    if not UC2_SQL.exists():
        _fail("uc2: SQL missing", f"expected {UC2_SQL}")
        return EXIT_FAIL, None
    rows = _bq_rows(UC2_SQL)
    if not rows:
        _fail("uc2: BigQuery returned zero rows", "run `make load-bq` then re-freeze (WR-09)")
        return EXIT_EMPTY, None
    distinct_dates = {r.get("call_date") for r in rows}
    if len(distinct_dates) < 2:
        _fail("uc2: fewer than 2 distinct call_date values", "widen the AIS window (WH-03)")
        return EXIT_EMPTY, None
    rows.sort(key=lambda r: (str(r.get("unlocode") or ""), str(r.get("call_date") or "")))
    body = {"use_case": "UC2", "store": "bigquery", "query": "sql/uc2_dwell_trend.sql",
            "row_count": len(rows), "distinct_call_dates": len(distinct_dates), "rows": rows}
    return EXIT_OK, body


# --------------------------------------------------------------------------- #
# UC3 / UC4 — credential-free Arango snapshots (analytics/snapshot_uc.py)        #
# --------------------------------------------------------------------------- #
def _freeze_uc3() -> tuple[int, dict | None]:
    from analytics.snapshot_uc import snapshot_uc3

    body = snapshot_uc3()
    impact = body.get("reroute_impact_suez") or {}
    if not impact.get("baseline_legs"):
        _fail("uc3: SUEZ reroute baseline path empty", "re-run `make load-arango` (foreign ports?)")
        return EXIT_EMPTY, None
    # Non-degeneracy DIRECTION assertions (never pin the 76.2h / 29->11 magnitudes).
    if not (float(impact.get("delta", 0)) > 0):
        _fail("uc3: SUEZ reroute delta not strictly positive",
              f"delta={impact.get('delta')} (expected > 0 — the hollow defect)")
        return EXIT_EMPTY, None
    closure = body.get("closure_gibraltar") or {}
    open_total = int(closure.get("open_reachable_total", 0) or 0)
    closed_total = int(closure.get("closed_reachable_total", 0) or 0)
    if open_total <= 0:
        _fail("uc3: GIBRALTAR closure baseline reachable total is zero", "re-run `make load-arango`")
        return EXIT_EMPTY, None
    if not (closed_total < open_total):
        _fail("uc3: GIBRALTAR closure did NOT reduce reachability",
              f"open={open_total} closed={closed_total} (expected strict decrease)")
        return EXIT_EMPTY, None
    return EXIT_OK, body


def _freeze_uc4() -> tuple[int, dict | None]:
    from analytics.snapshot_uc import snapshot_uc4

    body = snapshot_uc4()
    if not body.get("baseline_path"):
        _fail("uc4: baseline SHORTEST_PATH empty", "re-run `make load-arango` (foreign ports?)")
        return EXIT_EMPTY, None
    if not body.get("reroute_path") or len(body["reroute_path"]) <= 1:
        _fail("uc4: reroute path empty/degenerate", "SUEZ disabled-lane filter is a no-op (hollow defect)")
        return EXIT_EMPTY, None
    if body.get("reroute_path") == body.get("baseline_path") or not (float(body.get("delta", 0)) > 0):
        _fail("uc4: reroute delta not strictly positive",
              f"delta={body.get('delta')} (expected > 0)")
        return EXIT_EMPTY, None
    return EXIT_OK, body


_FREEZERS: dict[str, Callable[[], tuple[int, dict | None]]] = {
    "uc1": _freeze_uc1,
    "uc2": _freeze_uc2,
    "uc3": _freeze_uc3,
    "uc4": _freeze_uc4,
}


def freeze_one(uc: str) -> int:
    """Freeze a single UC golden. Returns an EXIT_* code; never overwrites on EMPTY/FAIL."""
    freezer = _FREEZERS[uc]
    try:
        code, body = freezer()
    except Exception as exc:  # noqa: BLE001
        # An import/connect failure surfaces as cluster/BQ unreachable, not a degenerate
        # write — and crucially never overwrites an existing valid golden (WR-09).
        _fail(f"{uc}: read failed (cluster/BQ unreachable?)", str(exc))
        return EXIT_CLUSTER_UNREACHABLE
    if code != EXIT_OK or body is None:
        return code
    _write_golden(uc, body)
    _ok(f"froze {_golden_path(uc).relative_to(REPO_ROOT)}",
        f"row/keys={sorted(body.keys())}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    selected = [a.lower() for a in argv if a.lower() in UC_NAMES] or list(UC_NAMES)
    worst = EXIT_OK
    for uc in selected:
        code = freeze_one(uc)
        if code != EXIT_OK:
            worst = code  # fail-fast on the most severe; keep the worst code
            _info(f"{uc}: NOT frozen (exit {code}) — existing golden left untouched")
    if worst == EXIT_OK:
        _info("commit subject: golden(lock): freeze uc1..uc4")
    return worst


if __name__ == "__main__":
    sys.exit(main())
