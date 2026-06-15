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
  Bronze: 0 = OK   1 = sha mismatch   2 = missing AIS   3 = idempotency drift
          4 = schema
  Silver:  5 = conformed-key coverage   6 = no port calls   7 = voyage-leg gate
           8 = identity DQ   9 = provenance coverage   10 = silver idempotency drift

The six Silver gates run AFTER the four Bronze gates (fail-fast, cheapest-first).
They read the landed silver/ objects with the gate_ais cloud-read idiom (lazy-import
pyarrow + google-cloud-storage, list_blobs(prefix="silver/..."), read counts) and
PRINT the demo/defense artifacts as ``[CITE]`` lines: the port-call count + the FINAL
calibrated radius/min-dwell (D-03 calibration artifact — PRINTed, not asserted to a
fixed number; threat T-04-14), the voyage-leg + zero-distance counts, the MMSI->IMO
collision + no-IMO drop counts (D-05/D-06), and 100% provenance coverage (D-11). The
idempotency gate re-runs ``silver.land_silver`` and asserts it lands 0 (write-once,
T-04-13). The four Bronze gates and their exit codes 0..4 are UNCHANGED.

Provenance: /Users/plosiewicz/Desktop/supply-chain/scripts/verify_synth.py
(gate_sha256 lines 99-191 + main orchestration); 03-RESEARCH.md § Verification /
Ship-Gate; 03-PATTERNS.md § scripts/verify.py gate substitutions; 04-VALIDATION.md
§ Ship-Gate Design (the six Silver gates); 04-PATTERNS.md § scripts/verify.py (EXTEND).
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

GATES: tuple[str, ...] = (
    "sha256",
    "schema",
    "idempotency",
    "ais",
    "silver_conformed_keys",
    "silver_port_calls",
    "silver_voyage_legs",
    "silver_identity_dq",
    "silver_provenance",
    "silver_idempotency",
)

# Bronze exit codes (UNCHANGED — 0..4).
EXIT_OK: int = 0
EXIT_SHA_MISMATCH: int = 1
EXIT_MISSING_AIS: int = 2
EXIT_IDEMPOTENCY_DRIFT: int = 3
EXIT_SCHEMA: int = 4

# Silver exit codes (NEW — distinct, continuing the sequence 5..10).
EXIT_SILVER_CONFORMED_KEYS: int = 5
EXIT_SILVER_NO_PORT_CALLS: int = 6
EXIT_SILVER_VOYAGE_LEGS: int = 7
EXIT_SILVER_IDENTITY_DQ: int = 8
EXIT_SILVER_PROVENANCE: int = 9
EXIT_SILVER_IDEMPOTENCY_DRIFT: int = 10

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

# --- Silver tier ---------------------------------------------------------- #
SILVER_PREFIX = "silver/"
SILVER_DIM_PREFIX = "silver/dim_"
SILVER_FACT_PORT_CALL_PREFIX = "silver/fact_port_call/"
SILVER_FACT_VOYAGE_LEG_PREFIX = "silver/fact_voyage_leg/"
# The four target US ports every conformed dim_port must carry (D-04).
TARGET_PORTS = ("USHOU", "USLAX", "USNYC", "USSAV")
# Valid provenance values every Silver row must carry (D-11).
VALID_PROVENANCE = {"real", "synthetic"}


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


# --------------------------------------------------------------------------- #
# Silver gates (exit codes 5..10) — read the landed silver/ objects             #
# --------------------------------------------------------------------------- #
def _silver_client_bucket():
    """Lazy-import the GCS client + Bronze/Silver bucket (gate_ais idiom).

    Returns ``(client, bucket)`` or ``(None, None)`` on an import/connect failure
    (the caller fails the gate gracefully — threat T-04-16: no uncaught traceback).
    """
    try:
        from google.cloud import storage
    except Exception as exc:  # noqa: BLE001
        _fail("silver: google-cloud-storage unavailable", str(exc))
        return None, None
    try:
        client = storage.Client(project="data-architecture-msds683")
        bucket = client.bucket(BRONZE_BUCKET)
        return client, bucket
    except Exception as exc:  # noqa: BLE001
        _fail("silver: Bronze/Silver unreachable", str(exc))
        return None, None


def _read_silver_table(client, bucket, blob):
    """Download one landed Silver Parquet blob into a pyarrow Table (defensive)."""
    import pyarrow.parquet as pq

    return pq.read_table(io.BytesIO(blob.download_as_bytes()))


def _list_parquet(client, bucket, prefix: str) -> list:
    """List landed ``.parquet`` blobs under a Silver prefix (sorted by name)."""
    return sorted(
        (b for b in client.list_blobs(bucket, prefix=prefix) if b.name.endswith(".parquet")),
        key=lambda b: b.name,
    )


def gate_silver_conformed_keys() -> bool:
    """Every dim_* row carries a valid conformed key + surrogate; 4 target ports present.

    Reads each landed ``silver/dim_*`` snapshot; asserts a surrogate_key column and a
    valid conformed natural key (UN/LOCODE for dim_port/dim_lane, valid-IMO via
    ``silver.imo.valid_imo`` for dim_vessel, SCAC for dim_carrier). PRINTs the overall
    conformed-key coverage % and verifies the four target US ports (D-04).
    """
    import pyarrow.parquet as pq  # noqa: F401

    from silver.imo import valid_imo

    client, bucket = _silver_client_bucket()
    if client is None:
        return False

    dim_blobs = [b for b in _list_parquet(client, bucket, SILVER_DIM_PREFIX)]
    if not dim_blobs:
        _fail("silver_conformed_keys: no landed dim_* objects", "run `make conform` first")
        return False

    total_rows = 0
    keyed_rows = 0
    seen_ports: set[str] = set()
    for blob in dim_blobs:
        table = _read_silver_table(client, bucket, blob)
        cols = set(table.column_names)
        if "surrogate_key" not in cols:
            _fail("silver_conformed_keys: missing surrogate_key", blob.name)
            return False
        n = table.num_rows
        total_rows += n
        if "unlocode" in cols:  # dim_port / dim_lane carry unlocode? dim_port does.
            vals = [v for v in table.column("unlocode").to_pylist() if v]
            keyed_rows += len(vals)
            seen_ports.update(vals)
        elif "lane_key" in cols:
            vals = [v for v in table.column("lane_key").to_pylist() if v]
            keyed_rows += len(vals)
        elif "imo" in cols:
            vals = [v for v in table.column("imo").to_pylist() if valid_imo(v)]
            keyed_rows += len(vals)
        elif "scac" in cols:
            vals = [v for v in table.column("scac").to_pylist() if v]
            keyed_rows += len(vals)
        else:
            _fail("silver_conformed_keys: no recognized conformed key", f"{blob.name}: cols={sorted(cols)}")
            return False

    coverage = (keyed_rows / total_rows * 100.0) if total_rows else 0.0
    missing_ports = [p for p in TARGET_PORTS if p not in seen_ports]
    if missing_ports:
        _fail("silver_conformed_keys: missing target port(s)", f"{missing_ports} not in dim_port")
        return False
    if keyed_rows != total_rows:
        _fail("silver_conformed_keys: incomplete coverage", f"{keyed_rows}/{total_rows} rows carry a valid conformed key")
        return False

    print(
        f"[CITE] Silver conformed-key coverage: {coverage:.1f}% "
        f"({keyed_rows}/{total_rows} dim rows); 4 target ports present {TARGET_PORTS}"
    )
    _ok("silver_conformed_keys gate: every dim row carries a valid conformed + surrogate key")
    return True


def gate_silver_port_calls() -> bool:
    """fact_port_call count > 0; PRINT count + the FINAL radius/min-dwell (D-03).

    The port-call count is a CALIBRATION artifact (D-03) — PRINTed, not asserted to a
    fixed number (threat T-04-14). Reads the radius/min-dwell from the land_silver
    documented constants so the deck cites the values that actually produced the count.
    """
    from silver.land_silver import MIN_DWELL_HOURS, RADIUS_NM

    client, bucket = _silver_client_bucket()
    if client is None:
        return False

    import pyarrow.parquet as pq

    blobs = _list_parquet(client, bucket, SILVER_FACT_PORT_CALL_PREFIX)
    if not blobs:
        _fail("silver_port_calls: no landed fact_port_call objects", "run `make derive` first")
        return False

    count = 0
    for blob in blobs:
        count += pq.read_metadata(io.BytesIO(blob.download_as_bytes())).num_rows

    if count <= 0:
        _fail("silver_port_calls: zero port calls derived", "geofence produced no calls — check radius/min-dwell calibration")
        return False

    n_days = len({b.name.split("dt=")[1].split("/")[0] for b in blobs if "dt=" in b.name})
    print(
        f"[CITE] Silver port calls: {count:,} fact_port_call rows at radius {RADIUS_NM} nm, "
        f"min-dwell {MIN_DWELL_HOURS} hr across {n_days} day(s) (D-03 calibration artifact)"
    )
    _ok("silver_port_calls gate: fact_port_call is non-empty")
    return True


def gate_silver_voyage_legs() -> bool:
    """fact_voyage_leg count; PRINT count + zero-distance-leg count (Pitfall 7)."""
    client, bucket = _silver_client_bucket()
    if client is None:
        return False

    blobs = _list_parquet(client, bucket, SILVER_FACT_VOYAGE_LEG_PREFIX)
    # A leg requires >=2 calls for the same vessel; an empty leg set is a valid (if
    # weak) slice outcome, so PRINT the count rather than hard-failing on zero.
    if not blobs:
        print("[CITE] Silver voyage legs: 0 fact_voyage_leg rows (no vessel made >=2 calls in the slice)")
        _ok("silver_voyage_legs gate: leg count reported (zero legs is a valid slice outcome)")
        return True

    total = 0
    zero_distance = 0
    for blob in blobs:
        table = _read_silver_table(client, bucket, blob)
        total += table.num_rows
        if "distance_nm" in table.column_names:
            zero_distance += sum(1 for d in table.column("distance_nm").to_pylist() if d == 0)

    print(
        f"[CITE] Silver voyage legs: {total:,} fact_voyage_leg rows "
        f"({zero_distance} zero-distance same-port leg(s) kept, Pitfall 7)"
    )
    _ok("silver_voyage_legs gate: leg count reported")
    return True


def gate_silver_identity_dq() -> bool:
    """PRINT the MMSI->IMO collision count + no-IMO drop count (D-05/D-06).

    Recomputes the first-class DQ metrics from the same column-projected Bronze AIS
    read the land step uses (``silver.land_silver.read_ais_fixes`` +
    ``silver.identity``) so the deck cites the exact collision/drop counts.
    """
    try:
        from silver import identity
        from silver.land_silver import read_ais_fixes
    except Exception as exc:  # noqa: BLE001
        _fail("silver_identity_dq: silver modules unavailable", str(exc))
        return False

    try:
        identity_rows, _ = read_ais_fixes(BRONZE_BUCKET)
    except Exception as exc:  # noqa: BLE001
        _fail("silver_identity_dq: Bronze AIS unreadable", str(exc))
        return False

    mapping, collisions = identity.resolve_mmsi_to_imo(identity_rows)
    all_mmsis = [r[0] for r in identity_rows]
    dropped = identity.dropped_mmsi_count(all_mmsis, mapping)

    print(
        f"[CITE] Silver identity DQ: {collisions} MMSI->IMO collision(s) (multi-IMO MMSI, D-05), "
        f"{dropped} no-IMO MMSI drop(s) (D-06); {len(set(mapping.values()))} distinct resolved IMO(s)"
    )
    _ok("silver_identity_dq gate: collision + no-IMO drop counts reported")
    return True


def gate_silver_provenance() -> bool:
    """100% of landed Silver rows carry provenance in {real, synthetic} (D-11)."""
    client, bucket = _silver_client_bucket()
    if client is None:
        return False

    blobs = _list_parquet(client, bucket, SILVER_PREFIX)
    if not blobs:
        _fail("silver_provenance: no landed silver/ objects", "run `make silver` first")
        return False

    total = 0
    valid = 0
    for blob in blobs:
        table = _read_silver_table(client, bucket, blob)
        if "provenance" not in table.column_names:
            _fail("silver_provenance: object missing provenance column", blob.name)
            return False
        for p in table.column("provenance").to_pylist():
            total += 1
            if p in VALID_PROVENANCE:
                valid += 1

    if total == 0:
        _fail("silver_provenance: no Silver rows to check", "silver/ objects are empty")
        return False
    if valid != total:
        _fail("silver_provenance: incomplete coverage", f"{valid}/{total} rows carry provenance in {VALID_PROVENANCE}")
        return False

    print(f"[CITE] Silver provenance coverage: 100% ({valid}/{total} rows carry provenance ∈ {VALID_PROVENANCE}) (D-11)")
    _ok("silver_provenance gate: every Silver row carries a valid provenance flag")
    return True


def gate_silver_idempotency() -> bool:
    """Re-invoke silver.land_silver and assert it lands NO new objects (write-once).

    upload_if_absent is write-once (D-06/D-09; threat T-04-13), so on an already-landed
    Silver the loader must report 0 landed / all skipped. Parses the loader's
    ``silver complete: N landed`` summary line (mirror gate_idempotency).
    """
    result = subprocess.run(
        [sys.executable, "-m", "silver.land_silver", "--bucket", BRONZE_BUCKET],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = result.stderr.splitlines()[-1] if result.stderr else "no stderr"
        _fail("silver_idempotency: land_silver re-run failed", tail)
        return False

    landed = None
    for line in result.stdout.splitlines():
        if "silver complete:" in line:
            try:
                landed = int(line.split("complete:")[1].split("landed")[0].strip())
            except (IndexError, ValueError):
                landed = None
            break

    if landed is None:
        _fail("silver_idempotency: could not parse loader summary", result.stdout.strip()[-200:])
        return False
    if landed != 0:
        _fail("silver_idempotency drift", f"re-run landed {landed} new object(s) — write-once contract violated (T-04-13)")
        return False

    _ok("silver_idempotency gate: Silver re-run landed 0 new objects (write-once, D-06/D-09)")
    return True


def main() -> int:
    print(f"[INFO] Bronze+Silver ship-gate — running gates: {', '.join(GATES)}")

    if not gate_sha256():
        return EXIT_SHA_MISMATCH
    if not gate_schema():
        return EXIT_SCHEMA
    if not gate_idempotency():
        return EXIT_IDEMPOTENCY_DRIFT
    if not gate_ais():
        return EXIT_MISSING_AIS

    # --- Silver gates (5..10) — run AFTER the Bronze gates, fail-fast ---------- #
    if not gate_silver_conformed_keys():
        return EXIT_SILVER_CONFORMED_KEYS
    if not gate_silver_port_calls():
        return EXIT_SILVER_NO_PORT_CALLS
    if not gate_silver_voyage_legs():
        return EXIT_SILVER_VOYAGE_LEGS
    if not gate_silver_identity_dq():
        return EXIT_SILVER_IDENTITY_DQ
    if not gate_silver_provenance():
        return EXIT_SILVER_PROVENANCE
    if not gate_silver_idempotency():
        return EXIT_SILVER_IDEMPOTENCY_DRIFT

    _ok("all gates", "Bronze + Silver pipeline verified (criteria 1, 2, 3, 4 proven)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
