"""scripts/freeze_criticality.py — freeze chokepoint-criticality invariants.

The Phase-7 demo-safety HOOK (GRAPHX-01 / D-03a). Reads the live ``chokepoints``
criticality fields written by ``analytics/run_criticality.py``, VALIDATES that ALL
rows are populated (not just ``rows[0]`` — WR-09: a partial cluster write must FAIL
the gate, never silently freeze an under-covered golden), SORTS rows by ``_key``
for byte-determinism (RESEARCH Pitfall 3 — cluster-storage row order is arbitrary
after writes/compactions), and writes a single-line, sorted, CREDENTIAL-FREE
invariant payload to ``criticality.golden.json`` at the repo root.

Scope (CONTEXT Deferred Ideas): this is ONLY the freeze hook. The full
demo-snapshot freeze + recorded backup capture is deferred to Phase 7 (DEL-01).
Build the hook now so the criticality artifact is demo-safe from day one.

Freezes INVARIANTS — chokepoint count, the most-critical chokepoint, a sorted
per-chokepoint criticality list, and a criticality tolerance range — NOT exact
stochastic floats beyond the rounded value the deterministic NetworkX path emits.
The golden carries ONLY counts/floats/strings — zero credentials (threat T-06-08 /
ASVS V7); it is allow-listed in ``.gitignore`` so it CAN be committed.

Byte-identical re-freeze (Pitfall 3 / WR-06): the ``frozen_at_iso`` field reuses
the prior committed timestamp when the rest of the body is unchanged, so
re-freezing against stable cluster state produces a byte-identical file.

Provenance: health360/scripts/freeze_gae.py (``_resolve_frozen_at_iso``
reuse-prior-timestamp byte-identity trick) + supply-chain/scripts/freeze_pagerank.py
(read-cluster -> validate-ALL-rows -> sort-by-_key -> write-golden, WR-05/WR-09).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from analytics.run_criticality import (
    ALGORITHM_NAME,
    CRITICALITY_ATTR,
    CRITICALITY_SEED,
    PROJECTION_NAME,
    RUN_META_PATH,
    TARGET_COLLECTION,
)
from lib.arango_client import MissingCredentialsError, get_db

EXIT_OK: int = 0
EXIT_FAIL: int = 1
EXIT_CRITICALITY_MISSING: int = 2
EXIT_CLUSTER_UNREACHABLE: int = 3

GOLDEN_PATH: Path = Path(__file__).resolve().parent.parent / "criticality.golden.json"


def _ok(label: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"[OK] {label}{suffix}")


def _fail(label: str, hint: str) -> None:
    print(f"[FAIL] {label}", file=sys.stderr)
    print(f"  hint: {hint}", file=sys.stderr)


def _info(label: str) -> None:
    print(f"[INFO] {label}")


def _resolve_frozen_at_iso(new_body: dict) -> str:
    """Reuse the prior frozen_at_iso when the body (minus the timestamp) is
    unchanged, so re-freezes are byte-identical (WR-06)."""
    if GOLDEN_PATH.exists():
        try:
            prior = json.loads(GOLDEN_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            prior = None
        if isinstance(prior, dict):
            prior_ts = prior.get("frozen_at_iso")
            prior_body = {k: v for k, v in prior.items() if k != "frozen_at_iso"}
            if isinstance(prior_ts, str) and prior_body == new_body:
                return prior_ts
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _read_run_path() -> str:
    """Producing-run path (gral|networkx) from the run-meta sidecar.

    Defaults to ``networkx`` (the de-facto primary path on this cluster, Pitfall
    1) when the sidecar is absent (e.g. a fresh checkout)."""
    try:
        meta = json.loads(RUN_META_PATH.read_text())
        path = meta.get("path")
        if path in {"gral", "networkx"}:
            return path
    except (OSError, json.JSONDecodeError):
        pass
    return "networkx"


def build_invariant_body(db) -> dict:
    """Construct the criticality.golden invariant body from live cluster state.

    Reads every ``chokepoints`` row, sorts by ``_key`` (Pitfall 3), and rolls the
    per-chokepoint criticality into deck-citable invariants. All floats are
    rounded so the golden is stable.
    """
    rows = list(
        db.aql.execute(
            f"FOR cp IN {TARGET_COLLECTION} "
            f"SORT cp._key "
            f"RETURN {{key: cp._key, crit: cp.@a}}",
            bind_vars={"a": CRITICALITY_ATTR},
        )
    )
    chokepoint_count = len(rows)
    # WR-09: validate ALL rows populated, not just rows[0] — a partial write FAILS.
    populated = sum(1 for r in rows if r.get("crit") is not None)

    # Sorted by _key (the AQL already SORTs; re-sort defensively for byte-stability).
    sorted_rows = sorted(
        (
            {"_key": r["key"], "criticality": round(float(r["crit"]), 12)}
            for r in rows
            if r.get("crit") is not None
        ),
        key=lambda r: r["_key"],
    )
    crit_values = [r["criticality"] for r in sorted_rows]
    # Most-critical = highest score, ties broken by _key ascending (total order).
    most_critical = (
        sorted(sorted_rows, key=lambda r: (-r["criticality"], r["_key"]))[0]["_key"]
        if sorted_rows
        else None
    )
    max_crit = max(crit_values) if crit_values else 0.0
    crit_range = [
        max(0.0, round(max_crit - 0.15, 2)),
        round(max_crit + 0.15, 2),
    ]

    return {
        "algorithm": ALGORITHM_NAME,
        "seed": CRITICALITY_SEED,
        "path": _read_run_path(),
        "projection": PROJECTION_NAME,
        "target_collection": TARGET_COLLECTION,
        "chokepoint_count": chokepoint_count,
        "populated_count": populated,
        "most_critical": most_critical,
        "max_criticality": round(max_crit, 12),
        "max_criticality_range": crit_range,
        "criticality_by_key": sorted_rows,
    }


def main() -> int:
    try:
        db = get_db(request_timeout=180)
    except MissingCredentialsError as exc:
        _fail(f"credentials: {exc}", "copy .env.template to .env and fill in values")
        return EXIT_CLUSTER_UNREACHABLE

    total = db.collection(TARGET_COLLECTION).count()
    if total == 0:
        _fail(
            f"{TARGET_COLLECTION} is empty",
            "run `make load-arango` then `python -m analytics.run_criticality` first",
        )
        return EXIT_CRITICALITY_MISSING

    body = build_invariant_body(db)
    # WR-09: a partial cluster write (e.g. update_many wrote some chokepoints and
    # crashed) must FAIL the gate, never silently freeze an under-covered golden.
    if body["populated_count"] != body["chokepoint_count"]:
        _fail(
            f"only {body['populated_count']}/{body['chokepoint_count']} chokepoints "
            f"have {CRITICALITY_ATTR} populated (partial cluster write?)",
            "run `python -m analytics.run_criticality` first to repopulate ALL "
            "chokepoints; investigate gral storeresults / update_many partial-write logs",
        )
        return EXIT_CRITICALITY_MISSING

    row = {"frozen_at_iso": _resolve_frozen_at_iso(body), **body}
    GOLDEN_PATH.write_text(json.dumps(row, sort_keys=True) + "\n")

    _ok(f"froze criticality.golden.json: {GOLDEN_PATH}", json.dumps(body, sort_keys=True))
    _info("commit subject: criticality(lock): freeze v1")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
