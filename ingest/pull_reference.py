"""Land the real port/location reference + chokepoint nodes (ING-01) into Bronze.

ING-01 / D-05 / D-06 / D-09. This module lands the three reference sets that are
the conformed-key backbone every later phase joins on (UN/LOCODE), shared by both
``dim_port`` (BigQuery) and the ArangoDB graph:

  - World Port Index (NGA Pub 150) -> carries the UN/LOCODE column directly (A3),
    landed under ``reference/wpi/pulled=YYYY-MM-DD/``. The direct NGA download is
    now WAF-gated to scripts (HTTP 403 "Request Rejected" — Pitfall 5, verified
    live 2026-06-14), so the loader attempts the scripted pull and FALLS BACK to
    the M1 sample at ``samples/world_port_index_pub150.csv`` on a 403/WAF reject.
    If neither path yields the file the loader exits with a clear message that the
    human-verify checkpoint (plan 03-03 Task 2) must supply it via a browser fetch.
  - UN/LOCODE canonical code list -> the scriptable GitHub mirror
    ``raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv``
    (UNECE is the source-of-record), landed under ``reference/unlocode/pulled=.../``.
  - Chokepoints -> the hand-authored 7-node set in ``reference/chokepoints.csv``
    (matching Phase-2 D-09 exactly), landed under the stable ``reference/chokepoints/``
    prefix (no ``pulled=`` — hand-authored, not fetched).

All three lands are idempotent (``lib.gcs.upload_if_absent`` no-op) and static
(D-05 stable / ``pulled=`` snapshot prefixes, NOT ``dt=`` date-partitioned).

Trust boundary (T-03-07): remote CSVs are untrusted; the WPI source-selection
fails loud on a WAF "Request Rejected" body rather than landing the HTML error
page as if it were the reference. The pure, network-free helpers
(``select_wpi_source`` / chokepoint shape) are unit-tested in
tests/test_pull_reference.py; the fetch + land flow only runs under the CLI.

Provenance: 03-RESEARCH.md § Reference & Priors Sourcing (ING-01) — WPI WAF 403
finding + mitigation, UN/LOCODE mirror URL + shape, the 7-node chokepoint
coordinate table; Pitfall 5. Idempotency primitive: lib.gcs.upload_if_absent
(landed in 03-01).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import requests

import lib.gcs

# --- UN/LOCODE: scriptable GitHub mirror (UNECE is source-of-record) --------- #
# 03-RESEARCH.md: 116,213 rows / 7,287,475 bytes; Country+Location(LOCODE) cols.
UNLOCODE_URL = (
    "https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv"
)

# --- World Port Index (NGA Pub 150): WAF-gated to scripts (Pitfall 5) -------- #
# The direct download 403s "Request Rejected" to curl/scripts (verified live
# 2026-06-14). The loader attempts it, then falls back to the M1 sample, then to
# the human-verify checkpoint. Pub 150 carries the UN/LOCODE column directly (A3).
WPI_URL = (
    "https://msi.nga.mil/api/publications/download"
    "?key=16920959/SFH00000/UpdatedPub150.csv&type=view"
)
WPI_PORTAL = "https://msi.nga.mil/Publications/WPI"
# M1 proof-of-pull artifact (gitignored under samples/) — the documented fallback.
WPI_M1_SAMPLE = Path("samples/world_port_index_pub150.csv")

# Markers in a WAF rejection body — if present, the bytes are NOT the reference.
WPI_WAF_MARKERS = ("Request Rejected", "support ID", "<html")

# --- Chokepoints: hand-authored, committed (T-03-08), stable prefix ---------- #
CHOKEPOINTS_LOCAL = Path("reference/chokepoints.csv")
CHOKEPOINT_KEYS = {
    "CHK_SUEZ",
    "CHK_PANAMA",
    "CHK_MALACCA",
    "CHK_GIBRALTAR",
    "CHK_BABMANDEB",
    "CHK_HORMUZ",
    "CHK_GOODHOPE",
}

BRONZE_BUCKET_DEFAULT = "data-architecture-msds683-bronze"
LOCAL_CACHE_DEFAULT = Path("data/reference")

REQUEST_TIMEOUT_S = 120


class WpiUnavailable(RuntimeError):
    """The WPI file could not be sourced from script or M1 sample.

    Raised so the CLI can exit with the human-verify-checkpoint guidance rather
    than landing a WAF error page (Pitfall 5 / T-03-07).
    """


# --------------------------------------------------------------------------- #
# Pure, network-free helpers (unit-tested)                                    #
# --------------------------------------------------------------------------- #
def looks_like_waf_rejection(body: bytes | str) -> bool:
    """True when ``body`` looks like a WAF "Request Rejected" page, not WPI CSV.

    A 200 that is actually an HTML rejection must NOT be landed as the reference
    (T-03-07: validate before landing). Decoded lossily so binary CSV bytes never
    raise here.
    """
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    return any(marker in text for marker in WPI_WAF_MARKERS)


def select_wpi_source(
    *,
    status_code: int,
    body: bytes | None,
    sample_path: Path = WPI_M1_SAMPLE,
    sample_exists: bool | None = None,
) -> tuple[str, bytes | None]:
    """Decide where the WPI bytes come from, given a scripted-fetch outcome.

    Returns ``(source, payload)`` where ``source`` is one of:
      - ``"fetched"``  — HTTP 200 with non-WAF bytes; ``payload`` is those bytes.
      - ``"m1_sample"`` — fetch was rejected (403/WAF or non-200) but the M1
        sample exists; ``payload`` is ``None`` (caller reads the sample file).
      - raises ``WpiUnavailable`` — neither path works; human-verify needed.

    This is the WPI-source-selection logic the plan's ``test_wpi_source_selection``
    asserts (200 -> fetched bytes; 403 -> M1 sample fallback, never crash). The
    ``sample_exists`` override lets tests avoid touching the filesystem.
    """
    exists = sample_path.exists() if sample_exists is None else sample_exists

    # Happy path: a genuine 200 that is NOT a WAF rejection page.
    if status_code == 200 and body is not None and not looks_like_waf_rejection(body):
        return "fetched", body

    # WAF reject (403 / "Request Rejected") or any non-usable response -> fall back.
    if exists:
        return "m1_sample", None

    raise WpiUnavailable(
        "WPI Pub 150 could not be fetched (the NGA download is WAF-gated to "
        f"scripts — HTTP {status_code}) and the M1 fallback {sample_path} is "
        "absent. The human-verify checkpoint (plan 03-03 Task 2) must supply "
        f"UpdatedPub150.csv via a browser fetch from {WPI_PORTAL} (or restore the "
        "M1 sample), then re-run `make pull-reference`."
    )


def validate_chokepoints(rows: list[dict[str, str]]) -> None:
    """Fail loud unless ``rows`` are exactly the 7 D-09 chokepoints with float coords.

    Guards the hand-authored reference against drift before landing: the key set
    must equal Phase-2 D-09 exactly (zero-rework graph projection in Phase 6) and
    every lat/lon must parse as a float (usable for GEO_DISTANCE node placement).
    """
    keys = {r["key"] for r in rows}
    if keys != CHOKEPOINT_KEYS:
        raise ValueError(
            f"chokepoints.csv key set {sorted(keys)} != the 7 Phase-2 D-09 nodes "
            f"{sorted(CHOKEPOINT_KEYS)}; refusing to land (graph would not conform)."
        )
    for r in rows:
        float(r["lat"])
        float(r["lon"])


# --------------------------------------------------------------------------- #
# Fetch + land flow (only under the CLI)                                       #
# --------------------------------------------------------------------------- #
def _try_fetch_wpi(
    session: requests.Session | None = None,
) -> tuple[int, bytes | None]:
    """Attempt the scripted WPI download; return ``(status_code, body | None)``.

    Never raises on the WAF/403 path — returns the status so ``select_wpi_source``
    can decide. Network errors degrade to ``(0, None)`` so the fallback fires.
    """
    getter = session.get if session is not None else requests.get
    try:
        resp = getter(WPI_URL, timeout=REQUEST_TIMEOUT_S)
        return resp.status_code, resp.content
    except requests.RequestException as exc:  # noqa: BLE001 - degrade to fallback
        print(f"[WARN] WPI scripted fetch failed ({exc!r}); trying M1 fallback.")
        return 0, None


def _read_chokepoint_rows(path: Path) -> list[dict[str, str]]:
    import csv

    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _land_bytes(
    payload: bytes,
    *,
    bucket: str,
    key: str,
    cache_dir: Path,
    name: str,
) -> bool:
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / name
    local_path.write_bytes(payload)
    return lib.gcs.upload_if_absent(bucket, key, str(local_path))


def _land_file(local_path: Path, *, bucket: str, key: str) -> bool:
    return lib.gcs.upload_if_absent(bucket, key, str(local_path))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ingest.pull_reference",
        description=(
            "Land the real port/location reference (World Port Index w/ UN/LOCODE), "
            "the canonical UN/LOCODE code list, and the hand-authored 7-node "
            "chokepoint set into GCS Bronze under reference/ stable prefixes. WPI is "
            "WAF-gated to scripts (Pitfall 5): the loader attempts the scripted pull, "
            "falls back to the M1 sample, then to the human-verify checkpoint. "
            "Idempotent write-once landing (ING-01 / D-05 / D-09)."
        ),
    )
    parser.add_argument(
        "--bucket", default=BRONZE_BUCKET_DEFAULT,
        help=f"Bronze bucket (default {BRONZE_BUCKET_DEFAULT}).",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=LOCAL_CACHE_DEFAULT,
        help=f"Local staging dir (default {LOCAL_CACHE_DEFAULT}; gitignored).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    today = dt.date.today().isoformat()
    session = requests.Session()
    print(
        f"[INFO] pull-reference: landing WPI/UN-LOCODE/chokepoints -> "
        f"gs://{args.bucket}/reference/ (pulled={today})"
    )

    landed = 0
    skipped = 0

    # --- UN/LOCODE (scriptable mirror; UNECE source-of-record) --------------- #
    resp = session.get(UNLOCODE_URL, timeout=REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    up = _land_bytes(
        resp.content, bucket=args.bucket,
        key=f"reference/unlocode/pulled={today}/code-list.csv",
        cache_dir=args.cache_dir / "unlocode", name="code-list.csv",
    )
    landed += int(up); skipped += int(not up)

    # --- WPI (scripted -> M1 sample -> human-verify checkpoint) -------------- #
    status, body = _try_fetch_wpi(session=session)
    try:
        source, payload = select_wpi_source(status_code=status, body=body)
    except WpiUnavailable as exc:
        print(f"[ERROR] {exc}")
        return 2  # distinct exit: WPI needs the human-verify checkpoint (Pitfall 5)

    wpi_key = f"reference/wpi/pulled={today}/world_port_index_pub150.csv"
    if source == "fetched":
        print("[INFO] WPI: scripted fetch succeeded (HTTP 200, non-WAF body).")
        assert payload is not None
        up = _land_bytes(
            payload, bucket=args.bucket, key=wpi_key,
            cache_dir=args.cache_dir / "wpi", name="world_port_index_pub150.csv",
        )
    else:  # m1_sample
        print(
            f"[INFO] WPI: scripted fetch rejected (HTTP {status} — WAF/Pitfall 5); "
            f"falling back to the M1 sample {WPI_M1_SAMPLE}."
        )
        up = _land_file(WPI_M1_SAMPLE, bucket=args.bucket, key=wpi_key)
    landed += int(up); skipped += int(not up)

    # --- Chokepoints (hand-authored; validate then land at stable prefix) ---- #
    rows = _read_chokepoint_rows(CHOKEPOINTS_LOCAL)
    validate_chokepoints(rows)
    up = _land_file(
        CHOKEPOINTS_LOCAL, bucket=args.bucket,
        key="reference/chokepoints/chokepoints.csv",
    )
    landed += int(up); skipped += int(not up)

    print(
        f"[INFO] pull-reference complete: {landed} landed, {skipped} skipped "
        f"(write-once no-op). WPI source: {source}. The 7-node chokepoint set "
        "matches Phase-2 D-09 (zero-rework Phase-6 graph projection)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
