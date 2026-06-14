"""scripts/generate.py — pure synthetic-data orchestrator (ING-03, D-12).

Analog: /Users/plosiewicz/Desktop/supply-chain/scripts/synth.py — sequential
generator orchestrator that writes JSONL via the canonical ``lib.jsonl.write_jsonl``
sink then freezes ``synthetic.sha256`` (the committed determinism contract).

Data-dependency order: read priors (conditioning) -> schedules -> bookings ->
container_events. Generators are PURE: this script writes LOCAL JSONL only;
landing into GCS Bronze is scripts/load_bronze.py's job (the Brambles
generator/loader split). ``synthetic.sha256`` is ALWAYS written to the committed
repo-root location regardless of ``--out-dir`` so the manifest matches whatever
JSONL set this run produced.

Determinism provenance recorded next to the manifest: Faker==40.1.2,
numpy==1.26.4, SEED=20240614 (Pitfall 3/4).

CLI: ``--seed INT`` (default lib.seeds.SEED), ``--out-dir PATH``.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from data_gen import bookings, container_events, schedules
from data_gen import network as net
from data_gen.conditioning import Conditioner
from lib.jsonl import write_jsonl
from lib.seeds import BOOKINGS_OFFSET, EVENTS_OFFSET, SCHEDULES_OFFSET, SEED

EXIT_OK = 0
EXIT_FAIL = 1

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR_DEFAULT = REPO_ROOT / "data" / "synthetic"
CHECKSUM_FILE = REPO_ROOT / "synthetic.sha256"
LOCAL_PRIORS_DEFAULT = REPO_ROOT / "data" / "priors"

# Full-volume targets (D-11). Unit tests use small counts directly on the
# generators; the orchestrator runs the real volume.
BOOKINGS_COUNT = 20_000
EVENTS_COUNT = 200_000


def _ok(label: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"[OK] {label}{suffix}")


def _fail(label: str, hint: str) -> int:
    print(f"[FAIL] {label}", file=sys.stderr)
    print(f"  hint: {hint}", file=sys.stderr)
    return EXIT_FAIL


def write_synthetic_sha256(out_dir: Path, checksum_path: Path) -> int:
    """Write POSIX ``sha256sum -c``-compatible manifest for ``*.jsonl`` in ``out_dir``.

    Sorted by filename (FS-enumeration-independent), TWO-space separator, LF
    endings + trailing LF. ``hashlib.file_digest`` (3.11+ stdlib). Returns line
    count. This is the committed determinism contract (criterion 3).
    """
    lines: list[str] = []
    for jsonl_path in sorted(out_dir.glob("*.jsonl")):
        with open(jsonl_path, "rb") as fh:
            digest = hashlib.file_digest(fh, "sha256").hexdigest()
        lines.append(f"{digest}  {jsonl_path.name}")
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scripts.generate",
        description=(
            "Generate the deterministic synthetic JSONL (schedules, bookings, "
            "container events) conditioned on the real priors, and freeze "
            "synthetic.sha256 (D-12 determinism contract). Pure: writes local "
            "JSONL only — Bronze landing is scripts.load_bronze."
        ),
    )
    parser.add_argument("--seed", type=int, default=SEED, help=f"Master seed (default {SEED}).")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR_DEFAULT, help=f"Local JSONL out dir (default {OUT_DIR_DEFAULT}; gitignored).")
    parser.add_argument("--priors-dir", type=Path, default=LOCAL_PRIORS_DEFAULT, help=f"Local priors cache (default {LOCAL_PRIORS_DEFAULT}).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] make generate: seed={args.seed} out_dir={args.out_dir}")
    print("[INFO] provenance: Faker==40.1.2, numpy==1.26.4 (determinism anchors, Pitfall 3/4)")

    counts: dict[str, int] = {}
    try:
        # 0. Read priors -> conditioning (ING-04). Port->country from the shared
        #    network constants (the four real AIS ports + bounded partner set).
        cond = Conditioner.from_local_cache(
            cache_dir=args.priors_dir, port_country=net.PORT_COUNTRY
        )

        # 1. schedules (depends only on conditioning).
        sched_rows = schedules.generate(seed=args.seed + SCHEDULES_OFFSET, cond=cond)
        counts["schedules"] = write_jsonl(args.out_dir / "schedules.jsonl", sched_rows)

        # 2. bookings (lanes weighted by lane_weight, ING-04).
        bk_rows = bookings.generate(
            seed=args.seed + BOOKINGS_OFFSET, cond=cond, count=BOOKINGS_COUNT
        )
        counts["bookings"] = write_jsonl(args.out_dir / "bookings.jsonl", bk_rows)

        # 3. container_events (LPI-conditioned delays; references bookings).
        ev_rows = container_events.generate(
            seed=args.seed + EVENTS_OFFSET,
            cond=cond,
            bookings_rows=bk_rows,
            count=EVENTS_COUNT,
        )
        counts["container_events"] = write_jsonl(
            args.out_dir / "container_events.jsonl", ev_rows
        )

        # 4. Freeze synthetic.sha256 (committed determinism contract, last step).
        n_lines = write_synthetic_sha256(args.out_dir, CHECKSUM_FILE)
    except Exception as exc:  # noqa: BLE001 — top-level orchestrator boundary
        return _fail("generate pipeline failed", str(exc))

    print("\n[OK] make generate: per-collection row counts")
    for k, v in counts.items():
        print(f"  - {k}: {v}")
    _ok(f"synthetic.sha256 written: {n_lines} lines", str(CHECKSUM_FILE))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
