"""scripts/load_bronze.py — idempotent synthetic JSONL -> GCS Bronze (D-04/D-05/D-06/D-09).

The files->Bronze step of the Brambles generator/loader split: scripts/generate.py
produces pure local JSONL (FLAT files, one per record type); this loader splits
each stream by **each record's own natural date** and lands the per-day shards
under their correct ``dt=`` partition via ``lib.gcs.upload_if_absent`` (write-once,
no-op-if-exists). A second run lands no duplicate objects — re-running converges
to the same Bronze state (D-06/D-09).

Per-day partitioning (D-05 dt= event-date partitioning; CR-03 fix):
  bookings.jsonl         -> synthetic/bookings/dt={booking_date}/bookings.jsonl
  container_events.jsonl -> synthetic/events/dt={event_ts date}/container_events.jsonl
  schedules.jsonl        -> synthetic/schedules/dt={SCHEDULE_ANCHOR_DT}/schedules.jsonl

Records are routed by:
  - events:    ``event_ts`` (ISO datetime) -> its calendar date (first 10 chars)
  - bookings:  ``booking_date`` (already ``YYYY-MM-DD``)
  - schedules: NO per-record date — proforma liner schedules are timeless
               (one-per-lane), so they land under a single quarter anchor
               partition. There is no event date to contradict, so this is not
               the CR-03 defect (which was *dated* records under a wrong dt=).

The split preserves the FLAT generated files byte-for-byte on disk (the
synthetic.sha256 freeze is on the flat files and is NOT touched); only the
landing/partitioning layer fans out per-day shards into a temp dir before upload.

Fail-loud if an expected JSONL is missing (run ``make generate`` first), or if a
record lacks its partition-date field. Wired to ``make load-bronze`` ->
``python -m scripts.load_bronze``. Generators stay pure; this is the only
synthetic files->Bronze step.

Provenance: lib.gcs.upload_if_absent (03-01); Brambles lib/import_runner.py
idempotent-loader discipline; 03-CONTEXT.md D-04/D-05/D-06/D-09; CR-03.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import lib.gcs
from data_gen.network import EVENT_PARTITION_DT

EXIT_OK = 0
EXIT_MISSING_FILE = 1
EXIT_BAD_RECORD = 2

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_DIR_DEFAULT = REPO_ROOT / "data" / "synthetic"
BRONZE_BUCKET_DEFAULT = "data-architecture-msds683-bronze"

# Schedules have no per-record natural date (proforma, one-per-lane). They land
# under a single quarter anchor partition — there is no event date to contradict.
SCHEDULE_ANCHOR_DT = EVENT_PARTITION_DT

# Local filename -> (Bronze sub-prefix, per-record date-field name OR None).
# date_field=None means "no natural date -> single SCHEDULE_ANCHOR_DT partition".
_FILE_SPEC: dict[str, tuple[str, str | None]] = {
    "bookings.jsonl": ("bookings", "booking_date"),
    "container_events.jsonl": ("events", "event_ts"),
    "schedules.jsonl": ("schedules", None),
}


def _strip_gs(bucket: str) -> str:
    """Accept either ``gs://name`` (Makefile) or a bare ``name``; return bare name."""
    if bucket.startswith("gs://"):
        return bucket[len("gs://"):].rstrip("/")
    return bucket.rstrip("/")


def _record_dt(record: dict, date_field: str | None, *, source: str) -> str:
    """Return the ``dt=`` partition date (``YYYY-MM-DD``) for one record.

    For a dated stream, read ``date_field`` and take its calendar date (first 10
    chars of the ISO value — handles both ``YYYY-MM-DD`` and ``YYYY-MM-DDTHH:MM:SS``).
    For an undated stream (``date_field is None``) return the schedule anchor.
    Fail loud if a dated record is missing/short on its date field — never route
    a record to a wrong or default partition silently (CR-03 contract).
    """
    if date_field is None:
        return SCHEDULE_ANCHOR_DT
    raw = record.get(date_field)
    if not isinstance(raw, str) or len(raw) < 10:
        raise ValueError(
            f"{source}: record missing/short {date_field!r} "
            f"(got {raw!r}) — cannot derive dt= partition (CR-03)."
        )
    return raw[:10]


def partition_records(lines: list[str], date_field: str | None, *, source: str) -> dict[str, list[str]]:
    """Group raw JSONL lines by their record's natural ``dt=`` date.

    Returns ``{dt: [raw_json_line, ...]}`` preserving input line order within each
    partition (deterministic). Blank lines are skipped. The raw line text is kept
    verbatim so a re-serialization round-trip cannot perturb byte content.
    """
    by_dt: dict[str, list[str]] = {}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        record = json.loads(line)
        dt_part = _record_dt(record, date_field, source=source)
        by_dt.setdefault(dt_part, []).append(line)
    return by_dt


def build_shards(in_dir: Path, shard_dir: Path) -> dict[Path, str]:
    """Split each flat JSONL into per-day shard files and map them to Bronze keys.

    Reads each flat ``in_dir/<filename>``, partitions its records by natural date,
    writes one shard file per ``dt=`` under ``shard_dir/<prefix>/dt=<date>/<filename>``,
    and returns ``{shard_local_path: bronze_key}``. The flat source files are read
    only — never modified — so the synthetic.sha256 freeze stays valid.
    """
    out: dict[Path, str] = {}
    for filename, (sub_prefix, date_field) in _FILE_SPEC.items():
        local_path = in_dir / filename
        lines = local_path.read_text(encoding="utf-8").splitlines()
        by_dt = partition_records(lines, date_field, source=filename)
        for dt_part, recs in sorted(by_dt.items()):
            shard_path = shard_dir / sub_prefix / f"dt={dt_part}" / filename
            shard_path.parent.mkdir(parents=True, exist_ok=True)
            # Newline-terminated JSONL; deterministic order from partition_records.
            shard_path.write_text("\n".join(recs) + "\n", encoding="utf-8")
            out[shard_path] = f"synthetic/{sub_prefix}/dt={dt_part}/{filename}"
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scripts.load_bronze",
        description=(
            "Idempotently land the generated synthetic JSONL into GCS Bronze under "
            "synthetic/{bookings,events,schedules}/dt=.../ via upload_if_absent "
            "(write-once, no-op-if-exists). Each record is routed to the dt= "
            "partition matching its OWN natural date (events by event_ts, bookings "
            "by booking_date; schedules are timeless -> single anchor). Run "
            "`make generate` first."
        ),
    )
    parser.add_argument("--in-dir", type=Path, default=IN_DIR_DEFAULT, help=f"Local generated-JSONL dir (default {IN_DIR_DEFAULT}).")
    parser.add_argument("--bucket", default=BRONZE_BUCKET_DEFAULT, help=f"Bronze bucket — accepts gs://name or bare name (default {BRONZE_BUCKET_DEFAULT}).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    bucket = _strip_gs(args.bucket)
    print(f"[INFO] load-bronze: {args.in_dir} -> gs://{bucket}/synthetic/ (per-record dt= partitioning)")

    # Fail loud if any expected flat JSONL is missing — never land a partial set.
    missing = [str(args.in_dir / fn) for fn in _FILE_SPEC if not (args.in_dir / fn).exists()]
    if missing:
        print(f"[FAIL] missing generated JSONL: {missing}", file=sys.stderr)
        print("  hint: run `make generate` first (generators are pure; this only lands).", file=sys.stderr)
        return EXIT_MISSING_FILE

    landed = 0
    skipped = 0
    with tempfile.TemporaryDirectory(prefix="ofa_load_bronze_") as tmp:
        try:
            mapping = build_shards(args.in_dir, Path(tmp))
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[FAIL] cannot partition synthetic records: {exc}", file=sys.stderr)
            return EXIT_BAD_RECORD

        for shard_path, key in sorted(mapping.items(), key=lambda kv: kv[1]):
            uploaded = lib.gcs.upload_if_absent(bucket, key, str(shard_path))
            if uploaded:
                landed += 1
                print(f"[OK] landed {key}")
            else:
                skipped += 1
                print(f"[SKIP] {key} (write-once, exists)")

    print(
        f"[INFO] load-bronze complete: {landed} landed, {skipped} skipped (write-once no-op) "
        f"across {landed + skipped} dt= shard object(s)."
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
