"""scripts/verify.py — Bronze ship-gate skeleton (Nyquist Wave-0 backbone).

Mirrors the Brambles verify_synth.py structure: fail-fast sequential gates run
cheapest-first, each returning a DISTINCT exit code per failure class so
``make verify`` is honestly RED until later plans land their inputs.

Gate sequence (cheapest, no-cloud first):
  1. sha256       — determinism proof: regenerate synthetic JSONL and compare
                    against the committed synthetic.sha256 manifest.
  2. schema       — assert synthetic records carry provenance + conformed keys.
  3. idempotency  — re-run a loader, assert object count is stable (write-once).
  4. ais          — AIS citation: sum pyarrow num_rows + blob.size for the
                    bounded 4-port 2024-Qx slice; print the citable total.

ALL FOUR are STUBS in this plan — their inputs do not yet exist:
  - synthetic.sha256 + the generators land in a later plan (03-05).
  - landed AIS objects land in 03-02.
  - the real gate bodies (sha256/idempotency/schema) are wired in 03-05.
Each stub prints a clear "[FAIL] <gate>: MISSING — provided by plan 03-0N" and
returns its exit code, so the skeleton runs offline and exits non-zero (honest red).

Exit codes are distinct per failure class (D-20-style):
  0 = OK (all gates passed — not reachable until the pipeline is complete)
  1 = sha256 mismatch (determinism regression)
  2 = missing AIS objects (ING-02 citation gate)
  3 = idempotency drift (write-once contract violated)
  4 = schema-presence failure (provenance / conformed keys absent)

Provenance: /Users/plosiewicz/Desktop/supply-chain/scripts/verify_synth.py
(GATES + exit-code map + main() orchestration); 03-PLAN.md Task 3;
03-PATTERNS.md § scripts/verify.py gate orchestration.
"""

from __future__ import annotations

import sys

GATES: tuple[str, ...] = ("sha256", "schema", "idempotency", "ais")

EXIT_OK: int = 0
EXIT_SHA_MISMATCH: int = 1
EXIT_MISSING_AIS: int = 2
EXIT_IDEMPOTENCY_DRIFT: int = 3
EXIT_SCHEMA: int = 4


def _ok(label: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"[OK] {label}{suffix}")


def _fail(label: str, hint: str) -> None:
    print(f"[FAIL] {label}", file=sys.stderr)
    print(f"  hint: {hint}", file=sys.stderr)


def gate_sha256() -> bool:
    """Determinism proof: regenerate synthetic JSONL and diff against the
    committed synthetic.sha256 manifest.

    STUB: the manifest + generators do not exist yet (provided by plan 03-05).
    Reports MISSING and fails so the gate is honestly red.
    """
    _fail("sha256", "MISSING — synthetic.sha256 manifest + generators provided by plan 03-05")
    return False


def gate_schema() -> bool:
    """Assert synthetic records carry a `provenance` field + conformed keys
    (UN/LOCODE, IMO, SCAC).

    STUB: synthetic records do not exist yet (provided by plan 03-05).
    """
    _fail("schema", "MISSING — synthetic records + schema check provided by plan 03-05")
    return False


def gate_idempotency() -> bool:
    """Re-run a loader and assert the landed object count is stable
    (lib.gcs.upload_if_absent no-op — write-once, D-06/D-09).

    STUB: nothing has been landed to re-load yet (loader provided by plan 03-05;
    inputs land via 03-02).
    """
    _fail("idempotency", "MISSING — loader + landed objects provided by plan 03-05 (inputs from 03-02)")
    return False


def gate_ais() -> bool:
    """AIS citation gate: sum pyarrow.parquet `num_rows` per landed file +
    blob.size bytes; print the citable "N rows / M bytes for the bounded
    4-port 2024-Qx slice". Fail if zero objects.

    STUB: no AIS objects are landed yet (provided by plan 03-02).
    """
    _fail("ais", "MISSING — landed AIS GeoParquet objects provided by plan 03-02")
    return False


def main() -> int:
    """Run gates cheapest-first; return the first failing gate's exit code.

    Returns EXIT_OK only if every gate passes (not reachable until the full
    pipeline lands its inputs).
    """
    print(f"[INFO] Bronze ship-gate — running gates: {', '.join(GATES)}")

    if not gate_sha256():
        return EXIT_SHA_MISMATCH
    if not gate_schema():
        return EXIT_SCHEMA
    if not gate_idempotency():
        return EXIT_IDEMPOTENCY_DRIFT
    if not gate_ais():
        return EXIT_MISSING_AIS

    _ok("all gates", "Bronze pipeline verified")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
