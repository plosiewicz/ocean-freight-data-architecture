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
import re
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
    "bq_fact_loaded",
    "bq_partition_cluster",
    "bq_idempotency",
    "uc1_nonnull",
    "uc2_trend",
    "graph_load",
    "xstore_count_parity",
    "xstore_semantic",
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

# BigQuery exit codes (NEW — distinct, continuing the sequence 11..15). The five BQ
# gates run AFTER the Silver gates (fail-fast, cheapest-first) and prove the loaded
# star end-to-end: fact loaded -> partitioned/clustered -> idempotent re-run -> UC1
# non-null -> UC2 trend. Bronze 0..4 / Silver 5..10 stay UNCHANGED.
EXIT_BQ_FACT_NOT_LOADED: int = 11
EXIT_BQ_IDEMPOTENCY_DRIFT: int = 12
EXIT_BQ_PARTITION_CLUSTER: int = 13
EXIT_UC1_NO_ROWS: int = 14
EXIT_UC2_NO_TREND: int = 15

# Graph + cross-store exit codes (NEW — distinct, continuing the sequence 16..18).
# These are the ETL-05 reconciliation gates. They run AFTER the 0..15 Bronze/Silver/BQ
# gates (Pitfall 5: a cross-store check must run only once BOTH sinks have loaded — the
# DAG verify task likewise fans in on BQ loads AND load_arango). They are the most
# expensive gates (they touch BOTH the managed ArangoDB cluster AND BigQuery) and are
# therefore last in the fail-fast ladder. Bronze 0..4 / Silver 5..10 / BQ 11..15 stay
# UNCHANGED.
EXIT_GRAPH_LOAD: int = 16  # ocean_network graph / collections absent or empty
EXIT_XSTORE_COUNT_PARITY: int = 17  # dim rows != vertex counts (shared-key mismatch)
EXIT_XSTORE_SEMANTIC: int = 18  # Suez-transiting-leg counts don't reconcile BQ<->Arango

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

# --- BigQuery tier (exit codes 11..15) ------------------------------------- #
BQ_PROJECT = "data-architecture-msds683"
BQ_DATASET = "ofa_star"
# Versioned UC SQL the gates run (Task 1, D-05) — read from disk, run as-is (T-05-11:
# static .sql, no user input -> no injection surface).
UC1_SQL = REPO_ROOT / "sql" / "uc1_eta_reliability.sql"
UC2_SQL = REPO_ROOT / "sql" / "uc2_dwell_trend.sql"
# The fact tables whose row counts the idempotency gate snapshots / re-counts.
BQ_FACT_TABLES = ("fact_voyage_leg", "fact_port_call")
# WR-05: the dim tables whose row counts the idempotency gate also snapshots / re-counts.
# dim_vessel/dim_carrier are now the MERGE targets (CR-02/CR-03), so the "MERGE dims are
# idempotent" claim must be MEASURED, not asserted — a MERGE that doubled dim_vessel on
# every run would otherwise pass a facts-only idempotency gate. dim_port/dim_lane +
# operated_by are WRITE_TRUNCATE snapshots; including them widens the idempotency proof.
BQ_DIM_TABLES = ("dim_vessel", "dim_carrier", "dim_port", "dim_lane", "operated_by")
# Every served table the idempotency gate proves stable across a re-run (facts + dims).
BQ_IDEMPOTENCY_TABLES = BQ_FACT_TABLES + BQ_DIM_TABLES
# Expected physical layout for the WH-01 partition/cluster gate (mirrors ddl_star.sql).
# WR-04: BOTH facts are partitioned on dt + clustered; assert each with its own keys
# (the gate previously checked only fact_voyage_leg, a verification blind spot).
BQ_PARTITION_COL = "dt"
BQ_EXPECTED_CLUSTER_KEYS = {
    "fact_voyage_leg": ("origin_unlocode", "dest_unlocode", "vessel_imo"),
    "fact_port_call": ("unlocode", "vessel_imo"),
}


def _ok(label: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"[OK] {label}{suffix}")


def _fail(label: str, hint: str) -> None:
    print(f"[FAIL] {label}", file=sys.stderr)
    print(f"  hint: {hint}", file=sys.stderr)


# WR-06: parse the loader's landed count ROBUSTLY rather than scraping prose with a
# brittle ``split("complete:")[1].split("landed")[0]`` (which a benign log reword
# silently breaks into a false negative, or worse mis-parses a number elsewhere into a
# false pass). Match a ``complete: <N> landed`` summary anywhere in the loader stdout
# with a tolerant regex (any whitespace, optional thousands separators between the
# keyword and the integer). Returns the int landed count or None when no summary line
# is present. The loader summary wording can drift without breaking the gate as long as
# it still contains "complete:" ... "<number>" ... "landed".
_LANDED_RE = re.compile(r"complete:\s*([\d,]+)\s+landed", re.IGNORECASE)


def _parse_landed_count(stdout: str) -> int | None:
    """Extract the landed object count from a loader's stdout (WR-06: robust)."""
    match = _LANDED_RE.search(stdout)
    if match is None:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


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

    # WR-06: parse the landed count robustly (tolerant regex), not by prose-splitting.
    landed = _parse_landed_count(result.stdout)
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
    sched_populated = 0
    for blob in blobs:
        table = _read_silver_table(client, bucket, blob)
        total += table.num_rows
        if "distance_nm" in table.column_names:
            zero_distance += sum(1 for d in table.column("distance_nm").to_pylist() if d == 0)
        if "schedule_delta" in table.column_names:
            sched_populated += sum(
                1 for s in table.column("schedule_delta").to_pylist() if s is not None
            )

    print(
        f"[CITE] Silver voyage legs: {total:,} fact_voyage_leg rows "
        f"({zero_distance} zero-distance same-port leg(s) — CR-01: same-port pairs are "
        f"excluded, so this should be 0)"
    )
    # WR-01 (RESOLVED in Plan 05-01 / D-02): real AIS legs are US->US, and US->US
    # proforma lanes are now emitted via the non-conditioner path (data_gen.network
    # US_US_LANES), so schedule_delta = actual - scheduled now MATCHES real US->US
    # legs. Report the live coverage; if a slice ever has zero matched lanes the
    # message degrades honestly to the historical WR-01 caveat.
    if sched_populated > 0:
        print(
            f"[CITE] Silver voyage legs: schedule_delta populated {sched_populated}/{total} "
            f"— schedule reliability IS answerable; US->US proforma lanes match the real "
            f"US->US AIS legs (D-02 / Pitfall 1 resolved)"
        )
    else:
        print(
            f"[CITE] Silver voyage legs: schedule_delta populated {sched_populated}/{total} "
            f"— no proforma lane matched the real legs in this slice (WR-01)"
        )
    _ok("silver_voyage_legs gate: leg count + schedule_delta coverage reported")
    return True


def gate_silver_identity_dq() -> bool:
    """PRINT the MMSI->IMO collision count + no-IMO drop count (D-05/D-06).

    Recomputes the first-class DQ metrics from the same column-projected Bronze AIS
    read the land step uses (``silver.land_silver.read_ais_fixes`` +
    ``silver.identity``) so the deck cites the exact collision/drop counts.
    """
    try:
        from silver import identity
        from silver.land_silver import _is_real_mmsi, read_ais_fixes
    except Exception as exc:  # noqa: BLE001
        _fail("silver_identity_dq: silver modules unavailable", str(exc))
        return False

    try:
        identity_rows, _ = read_ais_fixes(BRONZE_BUCKET)
    except Exception as exc:  # noqa: BLE001
        _fail("silver_identity_dq: Bronze AIS unreadable", str(exc))
        return False

    mapping, collisions = identity.resolve_mmsi_to_imo(identity_rows)
    # WR-06: same real-MMSI denominator as the land step (drop null/0/empty MMSIs
    # from the universe) so the deck-cited no-IMO drop count is not inflated.
    all_mmsis = [r[0] for r in identity_rows if _is_real_mmsi(r[0])]
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

    # WR-06: parse the landed count robustly (tolerant regex), not by prose-splitting.
    landed = _parse_landed_count(result.stdout)
    if landed is None:
        _fail("silver_idempotency: could not parse loader summary", result.stdout.strip()[-200:])
        return False
    if landed != 0:
        _fail("silver_idempotency drift", f"re-run landed {landed} new object(s) — write-once contract violated (T-04-13)")
        return False

    _ok("silver_idempotency gate: Silver re-run landed 0 new objects (write-once, D-06/D-09)")
    return True


# --------------------------------------------------------------------------- #
# BigQuery gates (exit codes 11..15) — query the loaded ofa_star star schema     #
# --------------------------------------------------------------------------- #
def _bq_client():
    """Lazy-import the BigQuery client (mirrors _silver_client_bucket; T-05-14 ADC).

    Returns a ``google.cloud.bigquery.Client`` or ``None`` on an import/connect
    failure (the caller fails the gate gracefully — no uncaught traceback, T-04-16).
    Auth is Application Default Credentials only — no key file, no committed secret.
    """
    try:
        from google.cloud import bigquery
    except Exception as exc:  # noqa: BLE001
        _fail("bq: google-cloud-bigquery unavailable", str(exc))
        return None
    try:
        return bigquery.Client(project=BQ_PROJECT)
    except Exception as exc:  # noqa: BLE001
        _fail("bq: BigQuery client init failed (check ADC)", str(exc))
        return None


def _bq_scalar(client, sql: str):
    """Run a single-value query and return its scalar (or raise on no rows)."""
    rows = list(client.query(sql).result())
    return rows[0][0] if rows else None


def gate_bq_fact_loaded() -> bool:
    """fact_voyage_leg row count > 0 in the loaded star (ETL-02).

    PRINTs a ``[CITE]`` count line for the deck. Fails if the table is empty or
    unreachable (the load never ran / failed).
    """
    client = _bq_client()
    if client is None:
        return False
    try:
        count = _bq_scalar(
            client,
            f"SELECT COUNT(*) FROM `{BQ_PROJECT}.{BQ_DATASET}.fact_voyage_leg`",
        )
    except Exception as exc:  # noqa: BLE001
        _fail("bq_fact_loaded: count query failed", str(exc))
        return False
    if not count or count <= 0:
        _fail(
            "bq_fact_loaded: fact_voyage_leg is empty",
            "run `make load-bq` (the warehouse DAG) to populate the star (ETL-02)",
        )
        return False
    print(
        f"[CITE] BQ fact loaded: {count:,} fact_voyage_leg rows in "
        f"{BQ_DATASET}.fact_voyage_leg (ETL-02)"
    )
    _ok("bq_fact_loaded gate: fact_voyage_leg is non-empty in the loaded star")
    return True


def gate_bq_partition_cluster() -> bool:
    """Assert BOTH facts are PARTITIONED on dt + CLUSTERED on their chosen FKs (WH-01).

    WR-04: the gate now iterates EVERY fact in BQ_EXPECTED_CLUSTER_KEYS (fact_voyage_leg
    AND fact_port_call), each with its own expected cluster keys — closing the prior
    blind spot where only fact_voyage_leg was verified and a mis-configured
    fact_port_call would keep every gate green. Reads each table DDL from
    INFORMATION_SCHEMA.TABLES (the authoritative physical-layout source) and asserts
    ``PARTITION BY dt`` plus a ``CLUSTER BY`` carrying that fact's expected keys. PRINTs
    a ``[CITE]`` metadata line per fact so the deck cites partition+cluster from
    metadata, not a claim.
    """
    client = _bq_client()
    if client is None:
        return False

    for table, cluster_keys in BQ_EXPECTED_CLUSTER_KEYS.items():
        try:
            ddl = _bq_scalar(
                client,
                f"SELECT ddl FROM `{BQ_PROJECT}.{BQ_DATASET}.INFORMATION_SCHEMA.TABLES` "
                f"WHERE table_name = '{table}'",
            )
        except Exception as exc:  # noqa: BLE001
            _fail("bq_partition_cluster: INFORMATION_SCHEMA query failed", f"{table}: {exc}")
            return False
        if not ddl:
            _fail(f"bq_partition_cluster: no DDL for {table}", "table missing — run `make ddl`")
            return False

        ddl_norm = " ".join(ddl.split())  # collapse newlines/indentation for matching
        partitioned = f"PARTITION BY {BQ_PARTITION_COL}" in ddl_norm
        clustered = "CLUSTER BY" in ddl_norm and all(k in ddl_norm for k in cluster_keys)
        if not partitioned:
            _fail(f"bq_partition_cluster: {table} not partitioned on dt", f"DDL: {ddl_norm[:200]}")
            return False
        if not clustered:
            _fail(
                f"bq_partition_cluster: {table} missing expected cluster keys",
                f"expected CLUSTER BY {cluster_keys}; DDL: {ddl_norm[:200]}",
            )
            return False

        print(
            f"[CITE] BQ physical layout: {table} PARTITION BY {BQ_PARTITION_COL} "
            f"+ CLUSTER BY {', '.join(cluster_keys)} (from INFORMATION_SCHEMA DDL) (WH-01)"
        )

    _ok(
        "bq_partition_cluster gate: both facts partition-on-dt + clustering confirmed "
        "from metadata (fact_voyage_leg + fact_port_call)"
    )
    return True


def gate_bq_idempotency() -> bool:
    """Snapshot fact+dim COUNT(*), re-run the BQ load leg, re-count, assert equal (ETL-04).

    Proves the re-run claim instead of asserting it (T-05-12): snapshots each table's
    row count, re-runs ``make load-bq`` (the warehouse DAG) via subprocess (mirror the
    gate_silver_idempotency subprocess pattern), re-counts, and asserts every count is
    unchanged. PRINTs a ``[CITE]`` "re-run row counts unchanged" line.

    WR-05: the snapshot set is now BQ_IDEMPOTENCY_TABLES (BOTH facts + the dims/bridge),
    not facts-only. dim_vessel/dim_carrier are the MERGE targets (CR-02/CR-03), so a
    MERGE that appended a duplicate version on every re-run is now caught here — the
    "MERGE dims are idempotent" CITE line is finally BACKED by a measurement.
    WR-06: counts come from a direct COUNT(*) query per table (robust to log wording),
    never from parsing a free-text loader summary line.
    """
    client = _bq_client()
    if client is None:
        return False

    def _counts() -> dict[str, int] | None:
        out: dict[str, int] = {}
        for tbl in BQ_IDEMPOTENCY_TABLES:
            try:
                out[tbl] = int(
                    _bq_scalar(client, f"SELECT COUNT(*) FROM `{BQ_PROJECT}.{BQ_DATASET}.{tbl}`")
                )
            except Exception as exc:  # noqa: BLE001
                _fail("bq_idempotency: count query failed", f"{tbl}: {exc}")
                return None
        return out

    before = _counts()
    if before is None:
        return False

    # Re-run the BQ load leg (the warehouse DAG). `make load-bq` runs `airflow dags
    # test` — a single creds-backed run, partition-overwrite facts + SCD1 dims +
    # staging->MERGE for the SCD2 dims (CR-02/CR-03 / D-04b).
    result = subprocess.run(
        ["make", "load-bq"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = result.stderr.splitlines()[-1] if result.stderr else "no stderr"
        _fail("bq_idempotency: `make load-bq` re-run failed", tail)
        return False

    after = _counts()
    if after is None:
        return False

    drifted = {
        t: (before[t], after[t]) for t in BQ_IDEMPOTENCY_TABLES if before[t] != after[t]
    }
    if drifted:
        _fail(
            "bq_idempotency drift",
            f"re-run changed row counts {drifted} — overwrite/MERGE not idempotent (ETL-04)",
        )
        return False

    fact_detail = ", ".join(f"{t}={before[t]:,}" for t in BQ_FACT_TABLES)
    dim_detail = ", ".join(f"{t}={before[t]:,}" for t in BQ_DIM_TABLES)
    print(
        f"[CITE] BQ idempotency: re-run row counts unchanged "
        f"(facts: {fact_detail}; dims: {dim_detail}) — partition-overwrite facts + "
        f"WRITE_TRUNCATE SCD1 dims + staging->MERGE SCD2 dims are idempotent (ETL-04 proven)"
    )
    _ok(
        "bq_idempotency gate: BQ load re-run left ALL fact + dim row counts unchanged "
        "(facts + dims, incl. the MERGE-target SCD2 dims)"
    )
    return True


def gate_uc1_nonnull() -> bool:
    """Run sql/uc1_eta_reliability.sql; assert >=1 row with non-NULL avg_delay_hours (WH-02)."""
    client = _bq_client()
    if client is None:
        return False
    if not UC1_SQL.exists():
        _fail("uc1_nonnull: UC1 SQL missing", f"expected {UC1_SQL}")
        return False
    sql = UC1_SQL.read_text(encoding="utf-8")
    try:
        rows = list(client.query(sql).result())
    except Exception as exc:  # noqa: BLE001
        _fail("uc1_nonnull: UC1 query failed", str(exc))
        return False
    nonnull = [r for r in rows if r["avg_delay_hours"] is not None]
    if not nonnull:
        _fail(
            "uc1_nonnull: UC1 returned no rows with a non-NULL avg_delay_hours",
            "schedule_delta is dead for this slice — check D-02 US->US proforma lanes (WH-02)",
        )
        return False
    print(
        f"[CITE] UC1 ETA reliability: {len(nonnull)} carrier/lane group(s) with non-NULL "
        f"avg_delay_hours (schedule reliability IS answerable, WH-02)"
    )
    _ok("uc1_nonnull gate: UC1 returns non-NULL schedule-reliability rows")
    return True


def gate_uc2_trend() -> bool:
    """Run sql/uc2_dwell_trend.sql; assert it spans >=2 distinct call_date values (WH-03)."""
    client = _bq_client()
    if client is None:
        return False
    if not UC2_SQL.exists():
        _fail("uc2_trend: UC2 SQL missing", f"expected {UC2_SQL}")
        return False
    sql = UC2_SQL.read_text(encoding="utf-8")
    try:
        rows = list(client.query(sql).result())
    except Exception as exc:  # noqa: BLE001
        _fail("uc2_trend: UC2 query failed", str(exc))
        return False
    distinct_dates = {r["call_date"] for r in rows}
    if len(distinct_dates) < 2:
        _fail(
            "uc2_trend: fewer than 2 distinct call_date values",
            f"got {len(distinct_dates)} date(s) — widen the AIS window (D-02a) for a trend (WH-03)",
        )
        return False
    print(
        f"[CITE] UC2 dwell trend: {len(rows)} port-day row(s) spanning {len(distinct_dates)} "
        f"distinct call_date(s) — turnaround/dwell trend IS answerable (WH-03)"
    )
    _ok("uc2_trend gate: UC2 returns a dwell trend across >=2 dates")
    return True


# --------------------------------------------------------------------------- #
# Graph + cross-store gates (exit codes 16..18) — reconcile the two sinks        #
# (ETL-05). Connect to the managed ArangoDB cluster ONLY via lib.arango_client   #
# (env creds, TLS-on); print only counts + [CITE] lines, never credentials       #
# (threat T-06-01b). The reconciliation LOGIC lives in scripts.xstore (pure,     #
# offline-tested); these gates only fetch live counts and delegate the compare.  #
# --------------------------------------------------------------------------- #

# The LOCKED named graph + collection set (mirrors lib.graph_loader — DO NOT
# re-decide here). The graph-load gate asserts each exists and is non-empty.
GRAPH_NAME = "ocean_network"
GRAPH_VERTEX_COLLECTIONS = ("ports", "vessels", "carriers", "lanes", "chokepoints")
GRAPH_EDGE_COLLECTIONS = ("route", "calls_at", "operates", "transits_chokepoint")
# (dim_name, vertex_collection, is_scd2) for the count-parity bridge. The SCD2 dims
# (dim_vessel/dim_carrier) count CURRENT rows only — the graph projects is_current
# vertices (lib.graph_loader filters is_current), so the BQ side must match.
XSTORE_DIM_VERTEX_PAIRS = (
    ("dim_port", "ports", False),
    ("dim_vessel", "vessels", True),
    ("dim_carrier", "carriers", True),
)


def _arango_db():
    """Lazy-connect to the managed ArangoDB cluster via lib.arango_client (TLS-on).

    Returns a python-arango DB handle or ``None`` on an import/credentials/connect
    failure (the caller fails the gate gracefully — no uncaught traceback, no creds
    in the message; threat T-06-01b). A larger request_timeout is used because the
    cross-store reconciliation issues whole-collection counts / a chokepoint traversal.
    """
    try:
        from lib.arango_client import MissingCredentialsError, get_db
    except Exception as exc:  # noqa: BLE001
        _fail("graph: lib.arango_client unavailable", str(exc))
        return None
    try:
        db = get_db(request_timeout=120)
        db.version()  # force the lazy connection so a bad URL/creds fails HERE
        return db
    except MissingCredentialsError as exc:
        _fail("graph: ARANGO_* credentials missing", str(exc))
        return None
    except Exception as exc:  # noqa: BLE001
        _fail("graph: managed cluster unreachable (check .env URL / TLS)", str(exc))
        return None


def gate_graph_load() -> bool:
    """Assert the ocean_network named graph + 5 vertex + 4 edge collections exist
    and are NON-EMPTY (the load_arango sink actually ran — ETL-05 sink #2).

    PRINTs a ``[CITE]`` per-collection count line for the deck. Fails (16) if the
    named graph is absent or any collection is empty (the load never ran / failed).
    """
    db = _arango_db()
    if db is None:
        return False
    try:
        if not db.has_graph(GRAPH_NAME):
            _fail(
                "graph_load: named graph absent",
                f"'{GRAPH_NAME}' not found — run `make load-arango` (ETL-05 sink #2)",
            )
            return False
        counts: dict[str, int] = {}
        for coll in GRAPH_VERTEX_COLLECTIONS + GRAPH_EDGE_COLLECTIONS:
            if not db.has_collection(coll):
                _fail("graph_load: collection absent", f"{coll} not found — load incomplete")
                return False
            counts[coll] = int(db.collection(coll).count())
    except Exception as exc:  # noqa: BLE001
        _fail("graph_load: cluster query failed", str(exc))
        return False

    empty = [c for c, n in counts.items() if n <= 0]
    if empty:
        _fail("graph_load: empty collection(s)", f"{empty} have 0 docs — re-run `make load-arango`")
        return False

    detail = ", ".join(f"{c}={n}" for c, n in counts.items())
    print(f"[CITE] Graph loaded: {GRAPH_NAME} populated ({detail}) (ETL-05 sink #2, GRAPH-01)")
    _ok("graph_load gate: ocean_network graph + 5 vertex + 4 edge collections non-empty")
    return True


def gate_xstore_count_parity() -> bool:
    """BQ dim row counts == Arango vertex counts on the shared keys (D-11, exit 17).

    For each (dim, vertex) pair the BigQuery row count (CURRENT rows only for the
    SCD2 dims) must equal the ArangoDB vertex collection count — the UN/LOCODE / IMO
    / SCAC bridge makes the correspondence 1:1. Delegates the compare to
    ``scripts.xstore.check_count_parity`` (the offline-tested pure logic). PRINTs a
    ``[CITE]`` parity line per dim citing the shared key.
    """
    from scripts.xstore import check_count_parity

    client = _bq_client()
    if client is None:
        return False
    db = _arango_db()
    if db is None:
        return False

    pairs: list[tuple[str, int, str, int]] = []
    try:
        for dim, vtx, is_scd2 in XSTORE_DIM_VERTEX_PAIRS:
            where = " WHERE is_current" if is_scd2 else ""
            bq_count = int(
                _bq_scalar(client, f"SELECT COUNT(*) FROM `{BQ_PROJECT}.{BQ_DATASET}.{dim}`{where}")
            )
            gr_count = int(db.collection(vtx).count())
            pairs.append((dim, bq_count, vtx, gr_count))
    except Exception as exc:  # noqa: BLE001
        _fail("xstore_count_parity: count query failed", str(exc))
        return False

    ok, mismatches = check_count_parity(pairs)
    if not ok:
        for m in mismatches:
            _fail("xstore_count_parity mismatch", m)
        return False

    for dim, bq_count, vtx, gr_count in pairs:
        print(
            f"[CITE] Cross-store parity: {dim}={bq_count:,} == {vtx}={gr_count:,} "
            f"(UN/LOCODE/IMO/SCAC shared-key bridge, D-11)"
        )
    _ok("xstore_count_parity gate: every conformed dim reconciles 1:1 with its graph vertex set")
    return True


def gate_xstore_semantic() -> bool:
    """Suez transit-share reconciles BQ<->Arango on the shared lane_key (D-11, exit 18).

    The Suez-transiting lane set is defined by the deterministic geographic rule
    (``lib.graph_loader.chokepoints_for_lane``) over the canonical ``data_gen.network.LANES``
    network — the single ground truth both sinks are projected from. The HARD check:
    the live Arango ``transits_chokepoint -> SUEZ`` edge count equals the rule's count
    (the graph projected exactly the rule's lanes). The BQ ``dim_lane`` overlap on the
    same ``lane_key``s is reported for the deck (real dim_lane holds only served lanes,
    so its overlap may be a subset — an honest gap, not a failure). Delegates the
    compare to ``scripts.xstore.check_semantic_suez`` (offline-tested pure logic).
    """
    from data_gen.network import LANES

    from lib.graph_loader import chokepoints_for_lane
    from scripts.xstore import SUEZ_KEY, check_semantic_suez, suez_lane_keys

    client = _bq_client()
    if client is None:
        return False
    db = _arango_db()
    if db is None:
        return False

    expected_keys = suez_lane_keys(LANES, chokepoints_for_lane)
    expected_count = len(expected_keys)

    try:
        # Arango: count transits_chokepoint edges whose _to is the SUEZ chokepoint
        # (AQL bind var — never f-string the chokepoint key; threat T-06-06 / ASVS V5).
        cursor = db.aql.execute(
            "RETURN LENGTH(FOR e IN transits_chokepoint "
            "FILTER e._to == @to RETURN 1)",
            bind_vars={"to": f"chokepoints/{SUEZ_KEY}"},
        )
        arango_suez = int(list(cursor)[0])
    except Exception as exc:  # noqa: BLE001
        _fail("xstore_semantic: Arango Suez traversal failed", str(exc))
        return False

    try:
        # BQ: how many of the canonical Suez lane_keys appear in served dim_lane
        # (parameterized UNNEST — typed query param, no string interpolation, T-05-07).
        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("keys", "STRING", expected_keys),
            ]
        )
        bq_overlap = int(
            list(
                client.query(
                    f"SELECT COUNT(*) FROM `{BQ_PROJECT}.{BQ_DATASET}.dim_lane` "
                    f"WHERE lane_key IN UNNEST(@keys)",
                    job_config=job_config,
                ).result()
            )[0][0]
        )
    except Exception as exc:  # noqa: BLE001
        _fail("xstore_semantic: BQ dim_lane overlap query failed", str(exc))
        return False

    ok, mismatches = check_semantic_suez(expected_count, arango_suez, bq_overlap)
    if not ok:
        for m in mismatches:
            _fail("xstore_semantic mismatch", m)
        return False

    print(
        f"[CITE] Cross-store semantic (Suez): rule-expected={expected_count} Suez lanes; "
        f"Arango transits_chokepoint->SUEZ={arango_suez} (reconciles); "
        f"BQ dim_lane lane_key overlap={bq_overlap} (shared lane_key bridge, D-11)"
    )
    _ok(
        "xstore_semantic gate: Suez transit-share reconciles across BigQuery and "
        "ArangoDB on the shared lane_key"
    )
    return True


def main() -> int:
    print(f"[INFO] Bronze+Silver+BQ+Graph ship-gate — running gates: {', '.join(GATES)}")

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

    # --- BQ gates (11..15) — run AFTER the Silver gates, fail-fast, cheapest-first.
    # Order: fact-loaded -> partition/cluster (metadata) -> idempotency (re-run load)
    # -> UC1 -> UC2. The idempotency gate is the most expensive (re-runs the DAG).
    if not gate_bq_fact_loaded():
        return EXIT_BQ_FACT_NOT_LOADED
    if not gate_bq_partition_cluster():
        return EXIT_BQ_PARTITION_CLUSTER
    if not gate_bq_idempotency():
        return EXIT_BQ_IDEMPOTENCY_DRIFT
    if not gate_uc1_nonnull():
        return EXIT_UC1_NO_ROWS
    if not gate_uc2_trend():
        return EXIT_UC2_NO_TREND

    # --- Graph + cross-store gates (16..18) — run AFTER the BQ gates, last in the
    # ladder (Pitfall 5: cross-store reconciliation requires BOTH sinks loaded; these
    # gates are the most expensive — they touch the managed cluster AND BigQuery).
    # Order: graph-loaded -> count-parity -> semantic Suez reconciliation.
    if not gate_graph_load():
        return EXIT_GRAPH_LOAD
    if not gate_xstore_count_parity():
        return EXIT_XSTORE_COUNT_PARITY
    if not gate_xstore_semantic():
        return EXIT_XSTORE_SEMANTIC

    _ok(
        "all gates",
        "Bronze + Silver + BQ + Graph slice verified end-to-end: fact loaded, "
        "partitioned+clustered, idempotent re-run, UC1 non-null, UC2 trend, "
        "ocean_network loaded, cross-store count-parity + Suez semantic reconciliation "
        "(criteria 1-4 + WH-01/02/03 + ETL-02/04/05 + GRAPH-01 proven)",
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
