"""scripts/load_bronze.py — idempotent synthetic JSONL -> GCS Bronze (D-04/D-06/D-09).

The files->Bronze step of the Brambles generator/loader split: scripts/generate.py
produces pure local JSONL; this loader maps each generated file to its
deterministic ``synthetic/`` Bronze key and lands it via
``lib.gcs.upload_if_absent`` (write-once, no-op-if-exists). A second run lands no
duplicate objects — re-running converges to the same Bronze state (D-06/D-09).

Key mapping (D-04 synthetic prefix, D-05 dt= partition):
  bookings.jsonl         -> synthetic/bookings/dt={dt}/bookings.jsonl
  container_events.jsonl -> synthetic/events/dt={dt}/container_events.jsonl
  schedules.jsonl        -> synthetic/schedules/dt={dt}/schedules.jsonl

Fail-loud if an expected JSONL is missing (run ``make generate`` first). Wired to
``make load-bronze`` -> ``python -m scripts.load_bronze``. Generators stay pure;
this is the only synthetic files->Bronze step.

Provenance: lib.gcs.upload_if_absent (03-01); Brambles lib/import_runner.py
idempotent-loader discipline; 03-CONTEXT.md D-04/D-05/D-06/D-09.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import lib.gcs
from data_gen.network import EVENT_PARTITION_DT

EXIT_OK = 0
EXIT_MISSING_FILE = 1

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_DIR_DEFAULT = REPO_ROOT / "data" / "synthetic"
BRONZE_BUCKET_DEFAULT = "data-architecture-msds683-bronze"

# Local filename -> Bronze sub-prefix under synthetic/ (note bookings/events/schedules).
_FILE_PREFIX: dict[str, str] = {
    "bookings.jsonl": "bookings",
    "container_events.jsonl": "events",
    "schedules.jsonl": "schedules",
}


def _strip_gs(bucket: str) -> str:
    """Accept either ``gs://name`` (Makefile) or a bare ``name``; return bare name."""
    if bucket.startswith("gs://"):
        return bucket[len("gs://"):].rstrip("/")
    return bucket.rstrip("/")


def bronze_key_map(in_dir: Path, *, dt: str) -> dict[Path, str]:
    """Map each expected local JSONL to its deterministic synthetic/ Bronze key.

    Keys follow D-04 (synthetic/ prefix) + D-05 (dt= partition). The local path is
    ``in_dir / <filename>``; the Bronze key is
    ``synthetic/<sub_prefix>/dt={dt}/<filename>``.
    """
    out: dict[Path, str] = {}
    for filename, sub_prefix in _FILE_PREFIX.items():
        local_path = in_dir / filename
        out[local_path] = f"synthetic/{sub_prefix}/dt={dt}/{filename}"
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scripts.load_bronze",
        description=(
            "Idempotently land the generated synthetic JSONL into GCS Bronze under "
            "synthetic/{bookings,events,schedules}/dt=.../ via upload_if_absent "
            "(write-once, no-op-if-exists). Run `make generate` first."
        ),
    )
    parser.add_argument("--in-dir", type=Path, default=IN_DIR_DEFAULT, help=f"Local generated-JSONL dir (default {IN_DIR_DEFAULT}).")
    parser.add_argument("--dt", default=EVENT_PARTITION_DT, help=f"Synthetic event partition date dt=YYYY-MM-DD (default {EVENT_PARTITION_DT}).")
    parser.add_argument("--bucket", default=BRONZE_BUCKET_DEFAULT, help=f"Bronze bucket — accepts gs://name or bare name (default {BRONZE_BUCKET_DEFAULT}).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    bucket = _strip_gs(args.bucket)
    mapping = bronze_key_map(args.in_dir, dt=args.dt)
    print(f"[INFO] load-bronze: {args.in_dir} -> gs://{bucket}/synthetic/ (dt={args.dt})")

    # Fail loud if any expected JSONL is missing — never land a partial set.
    missing = [str(p) for p in mapping if not p.exists()]
    if missing:
        print(f"[FAIL] missing generated JSONL: {missing}", file=sys.stderr)
        print("  hint: run `make generate` first (generators are pure; this only lands).", file=sys.stderr)
        return EXIT_MISSING_FILE

    landed = 0
    skipped = 0
    for local_path, key in mapping.items():
        uploaded = lib.gcs.upload_if_absent(bucket, key, str(local_path))
        if uploaded:
            landed += 1
            print(f"[OK] landed {local_path.name} -> {key}")
        else:
            skipped += 1
            print(f"[SKIP] {local_path.name} -> {key} (write-once, exists)")

    print(f"[INFO] load-bronze complete: {landed} landed, {skipped} skipped (write-once no-op).")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
