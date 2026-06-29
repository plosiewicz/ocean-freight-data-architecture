"""scripts/freeze_uc4_reliability.py — freeze the UC4 route-reliability SIDECAR.

This is the deterministic build step that turns the existing UC4 golden path hops
into a committable reliability aggregate, computed with the REAL cached World Bank
LPI / UNCTAD LSCI priors (``data/priors/``) — NOT the bounded UC4 fallback table.

Contract (mirrors scripts/freeze_uc.py's byte-determinism discipline):
  1. Read the source golden ``data/golden/uc4.golden.json`` (READ-ONLY — never mutate it;
     the byte-exact parity test in web/lib/arango.test.ts asserts its shape).
  2. Build a SINGLE real conditioner via ``analytics.route_reliability.default_conditioner()``
     with NO cache_dir override, so it resolves ``data/priors/`` from the process cwd. The
     script MUST run with cwd = repo root so ``data/priors/lpi/lpi.json`` /
     ``data/priors/lsci/lsci.json`` exist and the REAL priors load (else the bounded
     FALLBACK_LPI/FALLBACK_LSCI would be used — which this script deliberately avoids).
  3. Compute baseline_reliability over the golden's ``baseline_path`` hops and
     reroute_reliability over its ``reroute_path`` hops, feeding the hop dicts VERBATIM
     (``route_reliability`` reads ``hop["port"]`` directly), sharing the one conditioner.
  4. REUSE the source golden's ``frozen_at_iso`` verbatim (NO live clock) so the output is
     a pure function of committed inputs — a re-run yields a byte-identical file.
  5. Write ``data/golden/uc4-reliability.json`` as a sorted-keys JSON object carrying
     ``baseline_reliability`` + ``reroute_reliability`` + ``frozen_at_iso``.

This sidecar is a SEPARATE file from the UC4 golden — it adds NO key to uc4.golden.json,
so the parity test is unaffected. copy-server-assets.mjs ships it automatically
(data/golden/ -> web/server-assets/golden/ recursively).

Provenance: scripts/freeze_uc.py (the canonical freeze contract) +
analytics/route_reliability.py (the reliability math, called verbatim).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from analytics.route_reliability import default_conditioner, route_reliability

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
GOLDEN_DIR: Path = REPO_ROOT / "data" / "golden"
SOURCE_GOLDEN: Path = GOLDEN_DIR / "uc4.golden.json"
SIDECAR: Path = GOLDEN_DIR / "uc4-reliability.json"

EXIT_OK: int = 0
EXIT_FAIL: int = 1


def main(argv: list[str] | None = None) -> int:
    if not SOURCE_GOLDEN.exists():
        print(f"[FAIL] source golden missing: {SOURCE_GOLDEN}", file=sys.stderr)
        return EXIT_FAIL

    golden = json.loads(SOURCE_GOLDEN.read_text(encoding="utf-8"))

    # One shared conditioner — resolves data/priors/ from cwd (must be repo root).
    # default_conditioner() loads the REAL local priors when lpi.json + lsci.json exist;
    # if they are missing it would silently fall back, so guard explicitly here.
    priors_dir = Path("data") / "priors"
    if not (
        (priors_dir / "lpi" / "lpi.json").exists()
        and (priors_dir / "lsci" / "lsci.json").exists()
    ):
        print(
            "[FAIL] real priors not found relative to cwd "
            f"({priors_dir.resolve()}); run from the repo root so default_conditioner "
            "loads data/priors/ (not the bounded fallback).",
            file=sys.stderr,
        )
        return EXIT_FAIL

    cond = default_conditioner()

    baseline_reliability = route_reliability(golden["baseline_path"], conditioner=cond)
    reroute_reliability = route_reliability(golden["reroute_path"], conditioner=cond)

    body = {
        "baseline_reliability": baseline_reliability,
        "reroute_reliability": reroute_reliability,
        # Reuse the source golden's timestamp verbatim — no live clock (byte-determinism).
        "frozen_at_iso": golden["frozen_at_iso"],
    }

    # sort_keys for byte-stability; indent=2 for readability; trailing newline.
    SIDECAR.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    print(
        f"[OK] froze {SIDECAR.relative_to(REPO_ROOT)} "
        f"(baseline legs={len(baseline_reliability['legs'])}, "
        f"reroute legs={len(reroute_reliability['legs'])}, "
        f"baseline leg0 lpi={baseline_reliability['legs'][0]['lpi']})"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
