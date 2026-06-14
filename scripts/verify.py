"""scripts/verify.py — Bronze ship-gate (FINALIZED, criteria 2 & 3).

Mirrors the Brambles verify_synth.py structure: fail-fast sequential gates run
cheapest-first, each returning a DISTINCT exit code per failure class. With AIS
(03-02), reference (03-03), priors (03-04), and the synthetic tier (this plan)
all landed, ``make verify`` exits 0 — proving the two anchor success criteria.

Gate sequence (cheapest, no-cloud first):
  1. sha256       — determinism proof (criterion 3): regenerate the synthetic
                    JSONL into a tempdir via a subprocess and compare each file's
                    digest against the committed synthetic.sha256 manifest. Any
                    mismatch -> EXIT_SHA_MISMATCH with the offending filename.
                    This proves byte-identical-from-fresh-clone.
  2. schema       — assert sampled synthetic records carry provenance + conformed
                    keys (so Phase 4 can conform) -> EXIT_SCHEMA otherwise.
  3. idempotency  — re-invoke scripts.load_bronze and assert it lands NO new
                    objects (all write-once no-ops) -> EXIT_IDEMPOTENCY_DRIFT.
  4. ais          — AIS citation (criterion 2): sum pyarrow num_rows + blob.size
                    over the landed ais/dt=*/ slice; PRINT the citable total ->
                    EXIT_MISSING_AIS if zero.

The sha256 + schema gates are offline-ish (schema samples a local generated file
if present, else the landed Bronze object); ais + idempotency are cloud-touching.

Exit codes (distinct per failure class):
  0 = OK   1 = sha mismatch   2 = missing AIS   3 = idempotency drift   4 = schema

Provenance: /Users/plosiewicz/Desktop/supply-chain/scripts/verify_synth.py
(gate_sha256 lines 99-191 + main orchestration); 03-RESEARCH.md § Verification /
Ship-Gate; 03-PATTERNS.md § scripts/verify.py gate substitutions.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

GATES: tuple[str, ...] = ("sha256", "schema", "idempotency", "ais")

EXIT_OK: int = 0
EXIT_SHA_MISMATCH: int = 1
EXIT_MISSING_AIS: int = 2
EXIT_IDEMPOTENCY_DRIFT: int = 3
EXIT_SCHEMA: int = 4

REPO_ROOT = Path(__file__).resolve().parent.parent
SHA256_FILE = REPO_ROOT / "synthetic.sha256"
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"

from lib.seeds import SEED  # noqa: E402

BRONZE_BUCKET = "data-architecture-msds683-bronze"
AIS_PREFIX = "ais/"
SYNTHETIC_SAMPLE_PREFIXES = (
    "synthetic/bookings/",
    "synthetic/events/",
    "synthetic/schedules/",
)
# Conformed keys every synthetic record type must carry (so Phase 4 conforms).
REQUIRED_KEYS = ("provenance", "origin_unlocode", "dest_unlocode")


def _ok(label: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"[OK] {label}{suffix}")


def _fail(label: str, hint: str) -> None:
    print(f"[FAIL] {label}", file=sys.stderr)
    print(f"  hint: {hint}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Gate 1: sha256 determinism (criterion 3) — COPY of Brambles gate_sha256       #
# --------------------------------------------------------------------------- #
def gate_sha256() -> bool:
    """Regenerate synthetic JSONL into a tempdir and diff vs committed manifest.

    Reads expected hashes IN-MEMORY before the subprocess call so the on-disk
    synthetic.sha256 (which generate.py rewrites) doesn't poison the comparison.
    """
    if not SHA256_FILE.exists():
        _fail("synthetic.sha256 missing", "run `make generate` once to populate (D-12)")
        return False

    expected: dict[str, str] = {}
    for line in SHA256_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            _fail(f"malformed line in synthetic.sha256: {line!r}", "expected `<64-hex>  <filename>`")
            return False
        expected[parts[1].strip()] = parts[0].strip()

    if not expected:
        _fail("synthetic.sha256 has no entries", "regenerate via `make generate`")
        return False

    with tempfile.TemporaryDirectory(prefix="ofa_verify_sha_") as tmp:
        tmp_path = Path(tmp)
        result = subprocess.run(
            [sys.executable, "-m", "scripts.generate", "--seed", str(SEED), "--out-dir", str(tmp_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            tail = result.stderr.splitlines()[-1] if result.stderr else "no stderr"
            _fail(f"regenerator subprocess returncode={result.returncode}", tail)
            return False

        mismatches: list[str] = []
        for filename, expected_digest in sorted(expected.items()):
            fpath = tmp_path / filename
            if not fpath.exists():
                mismatches.append(f"{filename}: MISSING (expected {expected_digest[:12]}...)")
                continue
            with open(fpath, "rb") as fh:
                actual = hashlib.file_digest(fh, "sha256").hexdigest()
            if actual != expected_digest:
                mismatches.append(f"{filename}: actual={actual[:12]}... expected={expected_digest[:12]}...")

    if mismatches:
        for m in mismatches:
            _fail("sha256 mismatch", m)
        return False

    _ok(f"sha256 gate: {len(expected)} files byte-identical to synthetic.sha256 (criterion 3)")
    return True


# --------------------------------------------------------------------------- #
# Gate 2: schema-presence (provenance + conformed keys)                         #
# --------------------------------------------------------------------------- #
def _sample_local_first_line(filename: str) -> dict | None:
    p = SYNTHETIC_DIR / filename
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                return json.loads(line)
    return None


def _sample_bronze_first_line(bucket, prefix: str) -> dict | None:
    blobs = list(bucket.client.list_blobs(bucket, prefix=prefix, max_results=1))
    if not blobs:
        return None
    data = blobs[0].download_as_bytes()
    for raw in data.splitlines():
        line = raw.strip()
        if line:
            return json.loads(line)
    return None


def gate_schema() -> bool:
    """Assert sampled synthetic records carry provenance + conformed keys.

    Prefers the local generated JSONL (offline); falls back to sampling the
    landed Bronze object if local is absent.
    """
    samples: list[tuple[str, dict | None]] = []
    local_names = {"bookings": "bookings.jsonl", "events": "container_events.jsonl", "schedules": "schedules.jsonl"}

    bucket = None
    for label, fname in local_names.items():
        rec = _sample_local_first_line(fname)
        if rec is None and bucket is None:
            try:
                from google.cloud import storage  # lazy — offline-friendly
                bucket = storage.Client(project="data-architecture-msds683").bucket(BRONZE_BUCKET)
            except Exception as exc:  # noqa: BLE001
                _fail("schema: no local JSONL and Bronze unreachable", str(exc))
                return False
        if rec is None and bucket is not None:
            prefix = f"synthetic/{label}/" if label != "bookings" else "synthetic/bookings/"
            rec = _sample_bronze_first_line(bucket, prefix)
        samples.append((label, rec))

    for label, rec in samples:
        if rec is None:
            _fail("schema: no sample record", f"{label}: neither local nor Bronze record found")
            return False
        missing = [k for k in REQUIRED_KEYS if k not in rec]
        # schedules carry origin/dest + provenance but no booking-only keys — the
        # REQUIRED_KEYS set is common to all three record types.
        if missing:
            _fail("schema: missing conformed keys", f"{label}: missing {missing} in {rec!r}")
            return False
        if rec.get("provenance") != "synthetic":
            _fail("schema: provenance != 'synthetic'", f"{label}: {rec.get('provenance')!r}")
            return False

    _ok(f"schema gate: {len(samples)} synthetic record types carry provenance + conformed keys")
    return True


# --------------------------------------------------------------------------- #
# Gate 3: idempotency (re-run loader -> no new objects)                         #
# --------------------------------------------------------------------------- #
def gate_idempotency() -> bool:
    """Re-invoke scripts.load_bronze and assert it lands NO new objects.

    upload_if_absent is write-once (D-06/D-09), so on an already-landed Bronze the
    loader must report 0 landed / all skipped. Parses the loader's summary line.
    """
    result = subprocess.run(
        [sys.executable, "-m", "scripts.load_bronze", "--bucket", BRONZE_BUCKET],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = result.stderr.splitlines()[-1] if result.stderr else "no stderr"
        _fail("idempotency: load_bronze re-run failed", tail)
        return False

    # Find the summary line: "... complete: N landed, M skipped ..."
    landed = None
    for line in result.stdout.splitlines():
        if "load-bronze complete:" in line:
            try:
                landed = int(line.split("complete:")[1].split("landed")[0].strip())
            except (IndexError, ValueError):
                landed = None
            break

    if landed is None:
        _fail("idempotency: could not parse loader summary", result.stdout.strip()[-200:])
        return False
    if landed != 0:
        _fail("idempotency drift", f"re-run landed {landed} new object(s) — write-once contract violated")
        return False

    _ok("idempotency gate: synthetic Bronze re-run landed 0 new objects (write-once, D-06/D-09)")
    return True


# --------------------------------------------------------------------------- #
# Gate 4: AIS citation (criterion 2)                                            #
# --------------------------------------------------------------------------- #
def gate_ais() -> bool:
    """Sum pyarrow num_rows + blob.size over landed ais/dt=*/ and PRINT the total.

    The citable evidence for success criterion 2: "N rows / M bytes for the
    bounded 4-port 2024 slice". Fails if zero AIS objects are landed.
    """
    try:
        import pyarrow.parquet as pq
        from google.cloud import storage
    except Exception as exc:  # noqa: BLE001
        _fail("ais: pyarrow / google-cloud-storage unavailable", str(exc))
        return False

    try:
        client = storage.Client(project="data-architecture-msds683")
        bucket = client.bucket(BRONZE_BUCKET)
        blobs = [b for b in client.list_blobs(bucket, prefix=AIS_PREFIX) if b.name.endswith(".parquet")]
    except Exception as exc:  # noqa: BLE001
        _fail("ais: Bronze unreachable", str(exc))
        return False

    if not blobs:
        _fail("ais: no landed AIS objects", f"expected gs://{BRONZE_BUCKET}/{AIS_PREFIX}dt=*/...parquet (run `make pull-ais`)")
        return False

    total_rows = 0
    total_bytes = 0
    for blob in blobs:
        total_bytes += blob.size or 0
        # Read parquet metadata for num_rows (full download — files are small, ~1MB).
        meta = pq.read_metadata(io.BytesIO(blob.download_as_bytes()))
        total_rows += meta.num_rows

    n_days = len({b.name.split("dt=")[1].split("/")[0] for b in blobs if "dt=" in b.name})
    print(
        f"[CITE] AIS bounded 4-port 2024 slice: {total_rows:,} rows / {total_bytes:,} bytes "
        f"across {len(blobs)} object(s), {n_days} day(s) (success criterion 2)"
    )
    _ok("ais citation gate: landed AIS slice is non-empty and citable")
    return True


def main() -> int:
    print(f"[INFO] Bronze ship-gate — running gates: {', '.join(GATES)}")

    if not gate_sha256():
        return EXIT_SHA_MISMATCH
    if not gate_schema():
        return EXIT_SCHEMA
    if not gate_idempotency():
        return EXIT_IDEMPOTENCY_DRIFT
    if not gate_ais():
        return EXIT_MISSING_AIS

    _ok("all gates", "Bronze pipeline verified (criteria 2 & 3 proven)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
