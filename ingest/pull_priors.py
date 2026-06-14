"""Land the three real priors (ING-04 inputs) into GCS Bronze under ``priors/``.

ING-04 / D-07 / D-13. This module fetches the three RESEARCH-verified keyless
prior endpoints and lands each raw JSON response under a ``priors/`` snapshot
prefix so the synthetic generators (plan 03-05) read their conditioning inputs
from the lake and the whole pipeline is reproducible from Bronze:

  - UNCTAD LSCI  (liner connectivity)   -> World Bank Data360 ``UNCTAD_LSC``
  - World Bank LPI (logistics reliability) -> WB v2 indicator ``LP.LPI.OVRL.XQ``
  - UN Comtrade O-D (trade demand)       -> keyless public preview, BOUNDED

Per D-13 these priors are *conditioners*, never promoted to fact tables: plan
03-05 consumes them to compute lane weights (LSCI x LSCI x Comtrade) and delay
distributions (LPI). The Comtrade pull stays bounded (a handful of
reporter/partner/year combos, ``cmdCode=TOTAL``, import flow) to respect the
keyless ~1 req/sec / 500-records limits (Pitfall 6); an optional
``COMTRADE_API_KEY`` is read from ``os.environ`` ONLY and never committed
(T-03-10). Each response is validated as parseable JSON with the expected
top-level shape before landing (V5 input validation, T-03-11).

The pure, network-free helpers (``parse_lpi`` / ``build_comtrade_params`` /
``comtrade_headers``) are unit-tested in tests/test_pull_priors.py. The
fetch + land flow only runs under the ``__main__`` CLI.

Provenance: 03-RESEARCH.md § Reference & Priors Sourcing (ING-04) — endpoints +
shapes verified live 2026-06-14; Comtrade bounded-pull strategy; Pitfall 6;
§ Idempotent write-once landing. Idempotency primitive: lib.gcs.upload_if_absent
(landed in 03-01).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

import lib.gcs

# --- Verified keyless endpoints (live curl + JSON read, 2026-06-14) --------- #
# UNCTAD LSCI via World Bank Data360 (keyless; paginate skip/top if needed).
LSCI_URL = "https://data360api.worldbank.org/data360/data"
LSCI_DATABASE_ID = "UNCTAD_LSC"

# World Bank LPI overall score (1-5), keyless; some rows are null aggregates.
LPI_URL = "https://api.worldbank.org/v2/country/all/indicator/LP.LPI.OVRL.XQ"
LPI_DATE_DEFAULT = "2023"

# UN Comtrade O-D — keyless PUBLIC PREVIEW (C=commodities, A=annual, HS class).
COMTRADE_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
COMTRADE_KEY_ENV = "COMTRADE_API_KEY"
COMTRADE_KEY_HEADER = "Ocp-Apim-Subscription-Key"

# --- Bounded Comtrade param set (Pitfall 6) --------------------------------- #
# A small explicit reporter/partner/year set keyed to the four US ports' trade.
# Reporter 842 = USA; partners are the handful of lanes the four ports need.
COMTRADE_REPORTER_DEFAULT = "842"  # USA
COMTRADE_PARTNERS_DEFAULT = ["156", "392", "276", "410", "528"]  # CN, JP, DE, KR, NL
COMTRADE_PERIOD_DEFAULT = "2022"
COMTRADE_FLOW = "M"  # imports only — keeps the result set bounded
COMTRADE_CMDCODE = "TOTAL"  # aggregate commodity, never an all-commodities sweep

# Respect the keyless ~1 req/sec limit when issuing multiple calls (Pitfall 6).
COMTRADE_SLEEP_S = 1.0

BRONZE_BUCKET_DEFAULT = "data-architecture-msds683-bronze"
LOCAL_CACHE_DEFAULT = Path("data/priors")

REQUEST_TIMEOUT_S = 120


# --------------------------------------------------------------------------- #
# Pure, network-free helpers (unit-tested)                                    #
# --------------------------------------------------------------------------- #
def parse_lpi(payload: Any) -> list[dict[str, Any]]:
    """Filter a World Bank LPI v2 JSON payload to numeric country rows.

    The WB v2 indicator response is ``[metadata, [records...]]``. Aggregate
    rows (World, regions) carry a null ``value`` and/or empty ``countryiso3code``
    — drop those; keep only rows with a non-empty iso3 and a numeric value (the
    1-5 LPI score). This is the T-03-11 input-validation contract before landing.
    """
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise ValueError(
            "LPI response is not the expected [metadata, [records]] shape "
            f"(got {type(payload).__name__}). Refusing to land (V5/T-03-11)."
        )
    kept: list[dict[str, Any]] = []
    for row in payload[1]:
        if not isinstance(row, dict):
            continue
        iso3 = row.get("countryiso3code")
        value = row.get("value")
        if iso3 and isinstance(value, (int, float)):
            kept.append(row)
    return kept


def build_comtrade_params(
    *,
    reporter_code: str,
    partner_codes: list[str],
    period: str,
) -> dict[str, str]:
    """Build a BOUNDED Comtrade O-D query (Pitfall 6).

    Always ``cmdCode=TOTAL`` (aggregate commodity, never an all-commodities
    sweep) with an explicit comma-joined partner list (never the ``all`` wildcard)
    and a single reporter + period + import flow — so the keyless preview stays
    well inside the 500-records / ~1 req/sec ceiling.
    """
    if not partner_codes:
        raise ValueError("Comtrade pull must name explicit partner codes (Pitfall 6).")
    return {
        "reporterCode": reporter_code,
        "partnerCode": ",".join(partner_codes),
        "period": period,
        "cmdCode": COMTRADE_CMDCODE,
        "flowCode": COMTRADE_FLOW,
    }


def comtrade_headers() -> dict[str, str]:
    """Return Comtrade auth headers, reading the optional key from env ONLY.

    Keyless public preview is the default (no header). If ``COMTRADE_API_KEY`` is
    present in ``os.environ`` it is forwarded as the subscription-key header to
    raise the per-call ceiling — the key is never hard-coded or committed
    (T-03-10).
    """
    key = os.environ.get(COMTRADE_KEY_ENV)
    if key:
        return {COMTRADE_KEY_HEADER: key}
    return {}


def _validate_lsci(payload: Any) -> None:
    """Fail loud unless the LSCI payload has the expected top-level shape."""
    if not isinstance(payload, dict) or "data" not in payload and "count" not in payload:
        raise ValueError(
            "LSCI response missing expected top-level keys (data/count). "
            "Refusing to land (V5/T-03-11)."
        )


def _validate_comtrade(payload: Any) -> None:
    """Fail loud unless the Comtrade payload has the expected top-level shape."""
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError(
            "Comtrade response missing expected top-level 'data' key. "
            "Refusing to land (V5/T-03-11)."
        )


# --------------------------------------------------------------------------- #
# Fetch + land flow (only under the CLI)                                       #
# --------------------------------------------------------------------------- #
def _get_json(
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> Any:
    """HTTPS GET ``url`` and parse the body as JSON (never eval; T-03-11/V5)."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https prior endpoint: {url}")
    getter = session.get if session is not None else requests.get
    resp = getter(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()  # raises on non-JSON — fail loud rather than land garbage


def _land_json(
    obj: Any,
    *,
    bucket: str,
    key: str,
    cache_dir: Path,
    name: str,
) -> bool:
    """Write ``obj`` as JSON locally, then idempotently land it to Bronze.

    Returns ``True`` when uploaded, ``False`` when the object already existed
    (write-once no-op, D-06/D-09).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / name
    with open(local_path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    return lib.gcs.upload_if_absent(bucket, key, str(local_path))


def fetch_lsci(*, session: requests.Session | None = None) -> Any:
    """Fetch UNCTAD LSCI from World Bank Data360 (keyless), validated."""
    payload = _get_json(
        LSCI_URL, params={"DATABASE_ID": LSCI_DATABASE_ID}, session=session
    )
    _validate_lsci(payload)
    return payload


def fetch_lpi(*, date: str, session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Fetch + filter World Bank LPI overall (keyless); null aggregates dropped."""
    payload = _get_json(
        LPI_URL, params={"date": date, "format": "json", "per_page": "400"}, session=session
    )
    return parse_lpi(payload)


def fetch_comtrade(
    *,
    reporter_code: str,
    partner_codes: list[str],
    period: str,
    session: requests.Session | None = None,
) -> Any:
    """Fetch the BOUNDED Comtrade O-D preview (keyless or env-keyed), validated."""
    params = build_comtrade_params(
        reporter_code=reporter_code, partner_codes=partner_codes, period=period
    )
    payload = _get_json(
        COMTRADE_URL, params=params, headers=comtrade_headers(), session=session
    )
    _validate_comtrade(payload)
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ingest.pull_priors",
        description=(
            "Land the three real priors (UNCTAD LSCI, World Bank LPI, bounded UN "
            "Comtrade O-D) into GCS Bronze under priors/ as raw JSON snapshots. "
            "Keyless endpoints; optional COMTRADE_API_KEY read from env only; "
            "idempotent write-once landing (D-07/D-13)."
        ),
    )
    parser.add_argument("--bucket", default=BRONZE_BUCKET_DEFAULT, help=f"Bronze bucket (default {BRONZE_BUCKET_DEFAULT}).")
    parser.add_argument("--cache-dir", type=Path, default=LOCAL_CACHE_DEFAULT, help=f"Local staging dir (default {LOCAL_CACHE_DEFAULT}; gitignored).")
    parser.add_argument("--lpi-date", default=LPI_DATE_DEFAULT, help=f"LPI year (default {LPI_DATE_DEFAULT}).")
    parser.add_argument("--comtrade-reporter", default=COMTRADE_REPORTER_DEFAULT, help="Comtrade reporter code (default 842=USA).")
    parser.add_argument("--comtrade-partners", default=",".join(COMTRADE_PARTNERS_DEFAULT), help="Comma-separated Comtrade partner codes (bounded set).")
    parser.add_argument("--comtrade-period", default=COMTRADE_PERIOD_DEFAULT, help=f"Comtrade period/year (default {COMTRADE_PERIOD_DEFAULT}).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    today = dt.date.today().isoformat()
    session = requests.Session()
    print(f"[INFO] pull-priors: landing LSCI/LPI/Comtrade -> gs://{args.bucket}/priors/ (pulled={today})")

    landed = 0
    skipped = 0

    # --- LSCI ---
    lsci = fetch_lsci(session=session)
    up = _land_json(
        lsci, bucket=args.bucket, key=f"priors/lsci/pulled={today}/lsci.json",
        cache_dir=args.cache_dir / "lsci", name="lsci.json",
    )
    landed += int(up); skipped += int(not up)
    time.sleep(COMTRADE_SLEEP_S)

    # --- LPI (null aggregates filtered) ---
    lpi = fetch_lpi(date=args.lpi_date, session=session)
    print(f"[INFO] LPI: kept {len(lpi)} country rows (null aggregates dropped)")
    up = _land_json(
        lpi, bucket=args.bucket, key=f"priors/lpi/pulled={today}/lpi.json",
        cache_dir=args.cache_dir / "lpi", name="lpi.json",
    )
    landed += int(up); skipped += int(not up)
    time.sleep(COMTRADE_SLEEP_S)

    # --- Comtrade O-D (bounded; env-only optional key) ---
    partners = [p.strip() for p in args.comtrade_partners.split(",") if p.strip()]
    comtrade = fetch_comtrade(
        reporter_code=args.comtrade_reporter, partner_codes=partners,
        period=args.comtrade_period, session=session,
    )
    up = _land_json(
        comtrade, bucket=args.bucket, key=f"priors/comtrade/pulled={today}/comtrade_od.json",
        cache_dir=args.cache_dir / "comtrade", name="comtrade_od.json",
    )
    landed += int(up); skipped += int(not up)

    print(
        f"[INFO] pull-priors complete: {landed} landed, {skipped} skipped (write-once no-op). "
        "Priors are conditioners only — never promoted to facts (D-13)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
