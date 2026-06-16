"""`.env`-based ArangoDB connection factory + JWT helper for the managed cluster.

Provenance: cloned from the author's prior repo `health360/lib/arango_client.py`
(Phase-6 correction #4 / 06-PATTERNS.md "lib/arango_client.py — CLONE"). This is the
FIRST graph code in the Ocean Freight Forwarder repo; the connection/auth/TLS pattern
is proven prior art and reused rather than reinvented.

D-01: this module targets the team's MANAGED ArangoDB cloud cluster via ``ARANGO_URL``
(not a local CE single-node) — TLS is always on and there are no CE/single-node
assumptions. Credentials are read ONLY from a repo-root ``.env`` (no hardcoded URL,
username, or password — the hardcoded-default anti-pattern is forbidden, threat
T-06-01). TLS is always on (``verify_override=True``); a TLS error means the URL is
wrong and is surfaced, never suppressed (threat T-06-02 / ASVS V6). The module has NO
side effects at import time — every network/credential access happens inside a
function, so ``import lib.arango_client`` succeeds with no ``.env`` present.

The JWT and password are never logged or printed; only ``[OK]``-style confirmation
lines are emitted (threat T-06-03 / ASVS V3/V7). For this repo ``ARANGO_GRAPH``
resolves to ``ocean_network``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests
from arango import ArangoClient
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# The repo-root .env (lib/ is a direct child of the git root).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _REPO_ROOT / ".env"

# Required credential variables — no defaults; absence is a hard error.
# RESEARCH Pitfall 2 / 06-PATTERNS.md: use the PRIOR-REPO names, NOT the D-02
# parenthetical (ARANGO_ENDPOINT/USER/DB). Prior-repo names win.
_REQUIRED_VARS = (
    "ARANGO_URL",
    "ARANGO_USERNAME",
    "ARANGO_PASSWORD",
    "ARANGO_DATABASE",
    "ARANGO_GRAPH",
)

# GAE / cluster JWT auth endpoint (used by the gral HTTP API).
_AUTH_PATH = "/_open/auth"


class MissingCredentialsError(RuntimeError):
    """Raised when one or more required ``ARANGO_*`` env vars are missing or empty."""


def _load_env() -> dict[str, str]:
    """Load and validate the required credentials from the repo-root ``.env``.

    The repo-root ``.env`` is the source of truth: it is loaded with
    ``override=True`` so a stale value already exported in the shell cannot
    silently shadow the file (threat T-06-04 / config-integrity — a leftover
    ``export ARANGO_PASSWORD=...`` must NOT win over the valid value in ``.env``).
    Falls back to process env only for vars absent from ``.env``. Raises
    :class:`MissingCredentialsError` if any required variable is missing or empty.
    No hardcoded credential default is ever supplied (threat T-06-01).
    """
    if _ENV_PATH.is_file():
        load_dotenv(_ENV_PATH, override=True)

    config: dict[str, str] = {}
    missing: list[str] = []
    for var in _REQUIRED_VARS:
        value = os.environ.get(var, "").strip()
        if not value:
            missing.append(var)
        else:
            config[var] = value

    if missing:
        raise MissingCredentialsError(
            "Missing required ArangoDB credentials: "
            + ", ".join(missing)
            + f". Copy .env.template to {_ENV_PATH} and fill in the values "
            "(never hardcode credentials in source)."
        )

    return {
        "url": config["ARANGO_URL"].rstrip("/"),
        "username": config["ARANGO_USERNAME"],
        "password": config["ARANGO_PASSWORD"],
        "database": config["ARANGO_DATABASE"],
        "graph": config["ARANGO_GRAPH"],
    }


def get_client() -> ArangoClient:
    """Return an :class:`ArangoClient` with TLS verification ON.

    ``verify_override=True`` keeps TLS verification on; verification is never
    disabled (threat T-06-02 / ASVS V6). A TLS error here indicates a
    wrong/misconfigured URL and is surfaced to the caller, never relaxed.
    """
    cfg = _load_env()
    return ArangoClient(hosts=cfg["url"], verify_override=True)


def get_db(db_name: str | None = None, *, request_timeout: float | None = None) -> Any:
    """Return a ``python-arango`` database handle for ``db_name`` (or the .env DB).

    The connection is lazy: no request is sent until a method (e.g. ``db.version()``)
    is called, so this stays side-effect free at construction time.

    ``request_timeout`` (seconds) overrides the python-arango default (60s) for the
    HTTP read timeout — pass a larger value for heavy, non-streaming AQL (e.g. a
    full cross-store referential-integrity scan), where a 60s default would
    spuriously ``ReadTimeout``.
    """
    cfg = _load_env()
    name = db_name or cfg["database"]
    client_kwargs: dict[str, Any] = {"hosts": cfg["url"], "verify_override": True}
    if request_timeout is not None:
        client_kwargs["request_timeout"] = request_timeout
    client = ArangoClient(**client_kwargs)
    return client.db(name, username=cfg["username"], password=cfg["password"])


def get_jwt() -> str:
    """Fetch a JWT from ``/_open/auth`` using the ``.env`` credentials.

    Returns the raw token. The token is NEVER logged or printed — only an
    ``[OK] JWT obtained`` confirmation line is emitted (threat T-06-03).
    """
    cfg = _load_env()
    resp = requests.post(
        f"{cfg['url']}{_AUTH_PATH}",
        json={"username": cfg["username"], "password": cfg["password"]},
        verify=True,
        timeout=30,
    )
    resp.raise_for_status()
    jwt = resp.json().get("jwt")
    if not jwt:
        raise RuntimeError("Auth endpoint returned no 'jwt' field")
    logger.info("[OK] JWT obtained")
    return jwt


def jwt_headers(jwt: str | None = None) -> dict[str, str]:
    """Return an ``Authorization: bearer <jwt>`` header dict.

    If ``jwt`` is omitted, a fresh token is fetched via :func:`get_jwt`.
    """
    token = jwt or get_jwt()
    return {"Authorization": f"bearer {token}"}


def arango_url() -> str:
    """Return the cluster base URL from ``.env`` (never the credentials)."""
    return _load_env()["url"]


def request_with_retry(
    method: str,
    path: str,
    *,
    jwt: str | None = None,
    timeout: int = 60,
    **kwargs: Any,
) -> requests.Response:
    """Issue an authenticated request, re-fetching the JWT EXACTLY ONCE on 401.

    ``path`` is appended to the cluster base URL (``ARANGO_URL``). On the first
    ``401`` the JWT is re-fetched and the request is retried a single time
    (the JWT on this cluster expires after ~1h — RESEARCH Pitfall 6). Any other
    status is returned to the caller unchanged (the caller decides whether to
    ``raise_for_status``).
    """
    base = arango_url()
    url = path if path.startswith("http") else f"{base}{path}"

    token = jwt or get_jwt()
    headers = {**kwargs.pop("headers", {}), **jwt_headers(token)}
    resp = requests.request(method, url, headers=headers, verify=True, timeout=timeout, **kwargs)

    if resp.status_code == 401:
        # Token likely expired — re-fetch ONCE and retry.
        logger.info("[OK] JWT expired; re-fetching once and retrying")
        token = get_jwt()
        headers = {**headers, **jwt_headers(token)}
        resp = requests.request(method, url, headers=headers, verify=True, timeout=timeout, **kwargs)

    return resp
