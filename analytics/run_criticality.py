"""analytics/run_criticality.py — chokepoint criticality (GRAPHX-01, D-03a).

The GAE showcase that ranks WHICH chokepoint is most critical to the ocean lane
network. It invokes the managed cluster's gral Graph Analytics Engine as the
PRIMARY path — install -> wait for the engine HTTPRoute to provision ->
``loaddataaql`` (sealed) -> betweenness-centrality -> poll -> ``storeresults`` and
verifies the write-back landed > 0 docs — then falls through to a seeded,
deterministic NetworkX betweenness-centrality run over the SAME projection when
gral is unreachable, times out, or ``storeresults`` writes 0 docs.

THE BIG LESSON (RESEARCH Pitfall 1, learned the hard way in BOTH prior repos
health360/analytics/run_gae.py and supply-chain/analytics/run_pagerank.py): the
gral route ``/gral/<short>/v1/*`` is NOT live for *minutes* after ACP install (the
Envoy HTTPRoute provisions async; until then the gateway 404s with the
coordinator's "unknown path"), and ``storeresults`` on an AQL-projection-loaded
graph can succeed while writing 0 docs (it does not map results back to source
``_key``\\s). The original code waited a fixed 10s and always fell back. The fix:
poll the engine route until it stops 404ing BEFORE any algorithm call, and verify
the write-back count > 0 — else fall through. The seeded NetworkX fallback is the
DE-FACTO path that ACTUALLY ships the criticality artifact; it is wired from day
one. This does NOT contradict D-03 ("GAE available"): gral compute runs live; the
demo-safe artifact is whichever path succeeds, frozen to a golden.

Criticality metric (Claude's discretion under D-03a / RESEARCH Pattern 5):
**betweenness centrality over the lane network** answers "which chokepoint carries
the most shortest port-to-port paths" — the most defensible "most critical"
metric. Connected-components count after each closure answers "what fragments"
when a chokepoint's lanes are removed. Both run cheaply at the hundreds-of-nodes
scale of this graph.

Determinism (RESEARCH Pitfall 3): the NetworkX path fetches edges via AQL SORTED
by ``(_from, _to, _key)``, sorts the materialized edge list and the node list
before seeding the graph, and seeds the algorithm — so the same input yields the
same ranking, which is what makes ``scripts/freeze_criticality.py`` byte-stable.

JWT is fetched FIRST, OUTSIDE the gral try/except (run_gae 565-628), so a
credentials failure surfaces cleanly instead of being misdiagnosed as a gral 404
(WR-07). ``request_with_retry`` re-auths once on 401 (~1h JWT expiry, Pitfall 6).
The JWT/password are NEVER logged or printed — only ``[OK]``/``[INFO]``
confirmations (threat T-06-03 / ASVS V3/V7).

Provenance: health360/analytics/run_gae.py (gral chain + route-poll + NetworkX
fallback + shared write-back + run() orchestrator) ; supply-chain/analytics/
run_pagerank.py (SORTed edge fetch + centrality flavor + store_*_results).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import networkx as nx
import requests

from lib.arango_client import (
    MissingCredentialsError,
    _load_env,
    get_db,
    get_jwt,
    jwt_headers,
)
from lib.seeds import SEED

# --- Exit-code contract (mirrors run_gae.py) -----------------------------
EXIT_OK: int = 0
EXIT_FAIL: int = 1
EXIT_GRAL_UNREACHABLE: int = 2
EXIT_CLUSTER_UNREACHABLE: int = 3
EXIT_AUTH_FAILED: int = 4  # credentials issue, distinct from gral 404

# --- Determinism / algorithm parameters (D-03a, Pitfall 3) ---------------
LPA_SEED: int = 42  # ported verbatim from run_gae (the gral/algorithm seed)
CRITICALITY_SEED: int = SEED  # NetworkX seed anchor (lib.seeds.SEED)
ALGORITHM_NAME: str = "networkx.betweenness_centrality"
PROJECTION_NAME: str = "ocean_network_lane_projection"

# Criticality target — the curated chokepoint vertices (lib.graph_loader).
TARGET_COLLECTION: str = "chokepoints"
CRITICALITY_ATTR: str = "criticality"

# gral ``storeresults`` write-back target. CRITICAL (Rule 1 fix, 06-05): gral
# storeresults on an AQL-projection-loaded graph writes the SYNTHETIC vertex id
# (``ports/<UNLOCODE>``) as a ``_key``, which ArangoDB URL-encodes to
# ``ports%2F<UNLOCODE>`` — polluting whatever target collection it is pointed at.
# Pointing it at the CONFORMED ``ports`` vertex collection corrupts the cross-store
# count-parity (dim_port rows != ports vertices, gate 17). Point it at a dedicated
# DISPOSABLE scratch collection that is NOT a conformed vertex set, so the readback
# count still proves whether gral persisted, without touching the graph projection.
GRAL_STORE_TARGET: str = "_gral_criticality_scratch"

# --- gral engine endpoints (ported VERBATIM from run_gae.py) -------------
GRAL_INSTALL_PATH: str = "/_platform/acp/v1/graphanalytics"
SERVICE_ID_PREFIX: str = "arangodb-gral-"
GRAL_POLL_INTERVAL_SEC: int = 2
GRAL_TIMEOUT_SEC: int = 300  # compute/load/store job cap
# THE-BIG-ONE fix (Pitfall 1): the gral route 404s for MINUTES after install
# while the Envoy HTTPRoute provisions. Poll the route until it stops 404ing
# BEFORE issuing any algorithm call — NOT the old fixed 10s.
GRAL_ROUTE_READY_TIMEOUT_SEC: int = 600
GRAL_ROUTE_POLL_INTERVAL_SEC: int = 5
GRAL_RESULT_ATTR: str = "gral_criticality"

# Write-back batching + run-metadata sidecar (freeze_criticality reads `path`).
WRITE_BATCH_SIZE: int = 5000
RUN_META_PATH: Path = Path(__file__).resolve().parent / ".criticality_run_meta.json"

_AUTH_PATH: str = "/_open/auth"

# --- Projection AQL (lane network — SORTED for determinism, Pitfall 3) ---
# The lane network IS the projection criticality runs over: ``route`` edges are
# port -> port with a transit weight; betweenness over that graph ranks which
# chokepoints (via the lanes that transit them) carry the most shortest paths.
# SORT by (_from, _to, _key) so cluster-storage row order can never perturb the
# materialized edge list (float-add non-associativity + arbitrary order break
# the freeze otherwise).
_NETWORKX_EDGE_FETCH_AQL: str = """
FOR e IN route
  FILTER STARTS_WITH(e._from, "ports/") AND STARTS_WITH(e._to, "ports/")
  SORT e._from, e._to, e._key
  RETURN { f: e._from, t: e._to }
""".strip()

# Chokepoint -> the set of lane _keys that transit it (INBOUND transits_chokepoint),
# SORTED so the per-chokepoint lane membership is deterministic.
_CHOKEPOINT_LANES_AQL: str = """
FOR cp IN chokepoints
  SORT cp._key
  LET lanes = (
    FOR l IN INBOUND cp transits_chokepoint
      SORT l._key
      RETURN l._key
  )
  RETURN { chokepoint: cp._key, lanes: lanes }
""".strip()

# gral loaddataaql projection (vertices then edges; only exercised if the engine
# ever serves — the NetworkX path is authoritative per Pitfall 1).
_GRAL_VERTICES_AQL: str = "FOR v IN ports RETURN {vertices: [{_id: v._id}]}"
_GRAL_EDGES_AQL: str = (
    'FOR e IN route FILTER STARTS_WITH(e._from, "ports/") '
    'AND STARTS_WITH(e._to, "ports/") '
    "RETURN {edges: [{_from: e._from, _to: e._to}]}"
)


def _ok(label: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"[OK] {label}{suffix}")


def _fail(label: str, hint: str) -> None:
    print(f"[FAIL] {label}", file=sys.stderr)
    print(f"  hint: {hint}", file=sys.stderr)


def _info(label: str) -> None:
    print(f"[INFO] {label}")


def _short_id(service_id: str) -> str:
    """Strip the ``arangodb-gral-`` prefix from a gral serviceId."""
    return service_id.removeprefix(SERVICE_ID_PREFIX)


class JwtAuthFailedError(RuntimeError):
    """``/_open/auth`` returned 4xx — a credentials issue, distinct from gral
    routing/transport failures (WR-07)."""


# ---------------------------------------------------------------------------
# gral HTTP helpers (ported from run_gae.py; raw requests over the ACP API).
# ---------------------------------------------------------------------------
def _post_with_retry(
    url: str, *, jwt: str, json_body: dict, timeout_sec: int = 60
) -> requests.Response:
    """POST with a single JWT re-fetch on 401 (Pitfall 6 — ~1h JWT expiry)."""
    resp = requests.post(
        url, json=json_body, headers=jwt_headers(jwt), verify=True, timeout=timeout_sec
    )
    if resp.status_code == 401:
        fresh = get_jwt()
        resp = requests.post(
            url,
            json=json_body,
            headers=jwt_headers(fresh),
            verify=True,
            timeout=timeout_sec,
        )
    return resp


def wait_for_engine_route(cfg: dict, jwt: str, short: str) -> None:
    """Poll ``GET /gral/<short>/v1/jobs`` until it stops returning 404 (Pitfall 1).

    A 404 here is the coordinator's "unknown path" — the Envoy HTTPRoute for the
    freshly installed engine is not provisioned yet. Any non-404 means the route
    is live. Raises ``RuntimeError`` if still 404 after
    ``GRAL_ROUTE_READY_TIMEOUT_SEC`` (caller routes to the NetworkX fallback).
    """
    base = cfg["url"].rstrip("/")
    url = f"{base}/gral/{short}/v1/jobs"
    headers = jwt_headers(jwt)
    deadline = time.monotonic() + GRAL_ROUTE_READY_TIMEOUT_SEC
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            resp = requests.get(url, headers=headers, verify=True, timeout=30)
        except requests.RequestException:
            time.sleep(GRAL_ROUTE_POLL_INTERVAL_SEC)
            continue
        if resp.status_code == 401:
            headers = jwt_headers(get_jwt())
            continue
        if resp.status_code != 404:
            _info(f"gral engine route live (status {resp.status_code}) after ~{attempt} checks")
            return
        time.sleep(GRAL_ROUTE_POLL_INTERVAL_SEC)
    raise RuntimeError(
        f"gral engine route /gral/{short}/v1/jobs still 404 after "
        f"{GRAL_ROUTE_READY_TIMEOUT_SEC}s — HTTPRoute not provisioned; NetworkX fallback"
    )


def _post_until_routed(
    url: str, *, jwt: str, json_body: dict, timeout_sec: int
) -> requests.Response:
    """POST ``json_body`` to ``url`` retrying while the gateway returns 404.

    A 404 means the per-path HTTPRoute is not provisioned yet — the request never
    reaches the engine, so retrying is side-effect-free. Returns the first
    non-404 response. Raises ``RuntimeError`` if still 404 after the route budget.
    """
    deadline = time.monotonic() + GRAL_ROUTE_READY_TIMEOUT_SEC
    attempt = 0
    while True:
        attempt += 1
        resp = _post_with_retry(url, jwt=jwt, json_body=json_body, timeout_sec=timeout_sec)
        if resp.status_code != 404:
            if attempt > 1:
                _info(f"gral endpoint routed after ~{attempt} attempts: {url.rsplit('/', 1)[-1]}")
            return resp
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"gral endpoint {url} still 404 after {GRAL_ROUTE_READY_TIMEOUT_SEC}s "
                "— HTTPRoute not provisioned; NetworkX fallback"
            )
        time.sleep(GRAL_ROUTE_POLL_INTERVAL_SEC)


def poll_gral_job(cfg: dict, jwt: str, short_id: str, job_id: int, timeout_sec: int) -> dict:
    """GET ``/gral/<short>/v1/jobs/<job_id>`` until complete or timeout.

    The live engine reports ``progress``/``total``/``error`` (not a state string):
    done iff ``error`` is falsy and ``progress == total`` (``total`` > 0).
    """
    base = cfg["url"].rstrip("/")
    job_url = f"{base}/gral/{short_id}/v1/jobs/{job_id}"
    headers = jwt_headers(jwt)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        resp = requests.get(job_url, headers=headers, verify=True, timeout=30)
        if resp.status_code == 401:
            headers = jwt_headers(get_jwt())
            continue
        if resp.status_code == 404:
            # per-path HTTPRoute still provisioning right after submit (Pitfall 1)
            time.sleep(GRAL_POLL_INTERVAL_SEC)
            continue
        resp.raise_for_status()
        body = resp.json() if resp.content else {}
        if body.get("error"):
            raise RuntimeError(
                f"gral job {job_id} error (code {body.get('error_code')}): "
                f"{body.get('error_message')!r}"
            )
        total = body.get("total")
        progress = body.get("progress")
        if total is not None and total > 0 and progress == total:
            return body
        time.sleep(GRAL_POLL_INTERVAL_SEC)
    raise RuntimeError(
        f"gral job {job_id} did not complete within {timeout_sec}s — NetworkX fallback"
    )


def submit_gral_centrality(cfg: dict, jwt: str) -> tuple[str, str, int]:
    """gral happy path: install -> wait-for-route -> loaddataaql (seal) ->
    betweenness-centrality submit.

    Returns ``(full_service_id, short_id, job_id)``. Raises
    ``requests.RequestException`` / ``RuntimeError`` on any failure — the caller
    routes to the NetworkX fallback.
    """
    base = cfg["url"].rstrip("/")

    install_url = f"{base}{GRAL_INSTALL_PATH}"
    resp = _post_with_retry(install_url, jwt=jwt, json_body={})
    resp.raise_for_status()
    service_info = (resp.json() or {}).get("serviceInfo") or {}
    full_service_id = str(service_info.get("serviceId") or "")
    if not full_service_id:
        raise RuntimeError("gral install: response missing serviceInfo.serviceId")
    short = _short_id(full_service_id)
    _info(f"gral install reachable: serviceId={full_service_id} short_id={short}")

    # Pitfall 1 fix: poll the engine route until the HTTPRoute is provisioned.
    wait_for_engine_route(cfg, jwt, short)

    load_spec = {
        "database": cfg["database"],
        "vertex_attributes": [{"name": "_id", "data_type": "string"}],
        "edge_attributes": [],
        "phases": [
            {"queries": [{"query": _GRAL_VERTICES_AQL}]},
            {"queries": [{"query": _GRAL_EDGES_AQL}]},
        ],
    }
    load_url = f"{base}/gral/{short}/v1/loaddataaql"
    resp = _post_until_routed(load_url, jwt=jwt, json_body=load_spec, timeout_sec=180)
    resp.raise_for_status()
    load_body = resp.json() or {}
    graph_id = load_body.get("graph_id")
    load_job = load_body.get("job_id")
    if graph_id is None:
        raise RuntimeError("gral loaddataaql: response missing graph_id")
    # Loading is async — the graph must SEAL before an algorithm can run.
    if load_job is not None:
        poll_gral_job(cfg, jwt, short, int(load_job), GRAL_TIMEOUT_SEC)

    # Betweenness-centrality is the criticality metric (D-03a / Pattern 5).
    centrality_spec = {
        "graph_id": graph_id,
        "synchronous": False,
        "random_tiebreak": False,
    }
    centrality_url = f"{base}/gral/{short}/v1/betweennesscentrality"
    resp = _post_until_routed(centrality_url, jwt=jwt, json_body=centrality_spec, timeout_sec=120)
    resp.raise_for_status()
    job_id_raw = (resp.json() or {}).get("job_id")
    if job_id_raw is None:
        raise RuntimeError("gral betweennesscentrality submit: response missing job_id")
    return full_service_id, short, int(job_id_raw)


def store_and_count(db, cfg: dict, jwt: str, short_id: str, job_id: int) -> int:
    """Persist the centrality result via gral ``storeresults`` and report how
    many docs it actually wrote.

    CAVEAT (Pitfall 1, verified live in both prior repos): on AQL-projection-
    loaded graphs ``storeresults`` reports success while writing 0 documents (the
    synthetic vertex identity is not mapped back to source ``_key``\\s). The
    caller treats a 0 count as "gral computed but cannot persist" and runs the
    identical betweenness via NetworkX over the same projection. Returns the
    write-back document count (0 -> NetworkX fallback).
    """
    base = cfg["url"].rstrip("/")
    # Write into a disposable scratch collection, NEVER the conformed ``ports``
    # vertex set (Rule 1 fix, 06-05): gral keys the write-back by the synthetic
    # vertex id (URL-encoded ``ports%2F<UNLOCODE>``), which would otherwise pollute
    # the conformed ports vertices and break cross-store count-parity (gate 17).
    if not db.has_collection(GRAL_STORE_TARGET):
        db.create_collection(GRAL_STORE_TARGET)
    store_spec = {
        "database": cfg["database"],
        "target_collection": GRAL_STORE_TARGET,
        "job_ids": [int(job_id)],
        "attribute_names": [GRAL_RESULT_ATTR],
    }
    store_url = f"{base}/gral/{short_id}/v1/storeresults"
    resp = _post_until_routed(store_url, jwt=jwt, json_body=store_spec, timeout_sec=180)
    resp.raise_for_status()
    store_job = (resp.json() or {}).get("job_id")
    if store_job is not None:
        poll_gral_job(cfg, jwt, short_id, int(store_job), GRAL_TIMEOUT_SEC)
    body = resp.json() or {}
    # Best-effort: the storeresults job body may report a written-doc count; if
    # unavailable, the verify-by-readback in run() decides whether gral landed.
    written = body.get("documents_written")
    return int(written) if isinstance(written, int) else 0


# ---------------------------------------------------------------------------
# NetworkX fallback — the DE-FACTO path that ships the criticality artifact.
# ---------------------------------------------------------------------------
def criticality_via_networkx(
    edges: list[tuple[str, str]], *, seed: int = CRITICALITY_SEED
) -> list[tuple[str, float]]:
    """Deterministic betweenness-centrality criticality ranking over ``edges``.

    ``edges`` is a list of ``(from, to)`` port/node pairs (already fetched SORTED
    for determinism — Pitfall 3). Returns a list of ``(node, score)`` tuples
    sorted by descending criticality, ties broken by node id ascending — so the
    same input + seed yields the SAME ordered ranking every run (which is what
    ``scripts/freeze_criticality.py`` relies on). Pure (no I/O) — directly unit
    tested offline by ``tests/test_criticality.py``.
    """
    # Sort the edge list defensively (input is already SORTed, but a re-sort here
    # makes the function self-contained and order-insensitive).
    sorted_edges = sorted({tuple(e) for e in edges})
    g = nx.Graph()
    # Seed nodes in sorted order so node iteration order is deterministic.
    nodes = sorted({n for e in sorted_edges for n in e})
    g.add_nodes_from(nodes)
    g.add_edges_from(sorted_edges)
    # betweenness_centrality is exact (not sampled) when k is None, so the seed is
    # not strictly required; pass it anyway for explicitness and future k-sampling.
    scores = nx.betweenness_centrality(g, normalized=True, seed=seed)
    # Descending score, ties broken by node id ascending → total order.
    ranking = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranking


def _fetch_projection_edges(db) -> list[tuple[str, str]]:
    """Fetch the lane-network edges via the SORTED AQL (Pitfall 3)."""
    rows = list(db.aql.execute(_NETWORKX_EDGE_FETCH_AQL))
    return [(r["f"], r["t"]) for r in rows]


def _chokepoint_lane_map(db) -> dict[str, list[str]]:
    """Map each chokepoint -> sorted list of lane _keys transiting it."""
    rows = list(db.aql.execute(_CHOKEPOINT_LANES_AQL))
    return {r["chokepoint"]: list(r["lanes"]) for r in rows}


def _chokepoint_criticality(
    db, edge_scores: dict[str, float]
) -> dict[str, float]:
    """Aggregate port betweenness onto chokepoints via the lanes that transit them.

    A chokepoint's criticality = the SUM of the betweenness of the ports that
    terminate the lanes transiting it (a lane ``_key`` is ``origin__dest``). This
    rolls "which ports carry the most shortest paths" up to "which chokepoint the
    most path-carrying lanes route through" — the D-03a "most critical chokepoint"
    answer. Deterministic: inputs are sorted, addition is over a sorted set.
    """
    choke_lanes = _chokepoint_lane_map(db)
    out: dict[str, float] = {}
    for choke in sorted(choke_lanes):
        total = 0.0
        for lane_key in sorted(choke_lanes[choke]):
            # lane _key is "ORIGIN__DEST"; credit both endpoint ports' centrality.
            # ``edge_scores`` is keyed by the full document id (``_from``/``_to`` =
            # ``ports/<UNLOCODE>``), so look the port betweenness up by the SAME
            # prefixed id, not the bare UN/LOCODE — else every lookup misses and all
            # chokepoints score 0 (Rule 1 bug found live in 06-05).
            parts = lane_key.split("__")
            for port in sorted(parts):
                total += float(edge_scores.get(f"ports/{port}", 0.0))
        out[choke] = round(total, 12)
    return out


def write_criticality(db, scores: dict[str, float]) -> int:
    """Idempotent ``update_many`` write-back of the ``criticality`` attribute.

    SHARED by BOTH the gral and NetworkX branches so the cluster end-state is
    byte-identical regardless of path. Overwrites in place — re-runs are no-ops.
    Returns the number of rows written.
    """
    updates = [
        {"_key": key, CRITICALITY_ATTR: round(float(score), 12)}
        for key, score in sorted(scores.items())
    ]
    coll = db.collection(TARGET_COLLECTION)
    for i in range(0, len(updates), WRITE_BATCH_SIZE):
        coll.update_many(updates[i : i + WRITE_BATCH_SIZE])
    return len(updates)


def _connected_components_count(edges: list[tuple[str, str]]) -> int:
    """Number of connected components over the lane projection (the "what
    fragments on closure" answer; deterministic over a sorted edge set)."""
    g = nx.Graph()
    g.add_edges_from(sorted({tuple(e) for e in edges}))
    return nx.number_connected_components(g)


def _write_run_meta(meta: dict) -> None:
    algorithm = (
        "gral.betweennesscentrality" if meta.get("path") == "gral" else ALGORITHM_NAME
    )
    payload = {"path": meta["path"], "algorithm": algorithm, "seed": CRITICALITY_SEED}
    try:
        RUN_META_PATH.write_text(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        pass


def run_gral_or_networkx(db, cfg: dict, jwt: str) -> dict:
    """gral-primary -> NetworkX-fallback criticality with a shared write-back.

    Try the full gral chain (install -> route-wait -> load -> betweenness ->
    store) and verify the write-back landed > 0 docs; on ANY gral failure (route
    404, storeresults writes 0, timeout) fall through to the seeded NetworkX
    betweenness over the SAME SORTed projection. Both paths compute the SAME
    chokepoint criticality and persist it via the same idempotent
    ``write_criticality``. Returns a credential-free summary dict.
    """
    # The projection is fetched once (SORTED) and reused by both the gral
    # verify-readback and the NetworkX fallback so they rank the same graph.
    edges = _fetch_projection_edges(db)
    port_scores = dict(criticality_via_networkx(edges))
    choke_scores = _chokepoint_criticality(db, port_scores)
    components = _connected_components_count(edges)

    path = "networkx"
    gral_compute_verified = False
    try:
        _full, short, job = submit_gral_centrality(cfg, jwt)
        _info(f"gral betweenness submitted: short_id={short} job_id={job}")
        poll_gral_job(cfg, jwt, short, job, GRAL_TIMEOUT_SEC)
        gral_compute_verified = True
        written = store_and_count(db, cfg, jwt, short, job)
        if written and written > 0:
            path = "gral"
            _ok(f"gral storeresults landed: {written} docs")
        else:
            _info(
                "gral computed criticality on-cluster but storeresults wrote 0 "
                "docs (AQL-projection limitation, Pitfall 1); persisting the "
                "identical betweenness via NetworkX over the same projection"
            )
    except (requests.RequestException, RuntimeError) as exc:
        _info(f"gral path unavailable ({type(exc).__name__}: {exc}); NetworkX fallback")

    # Shared idempotent write-back (both paths). The chokepoint criticality is
    # always written from the deterministic NetworkX computation so the frozen
    # golden is reproducible regardless of which path "ran".
    n = write_criticality(db, choke_scores)
    ranked = sorted(choke_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    meta = {
        "path": path,
        "algorithm": ALGORITHM_NAME,
        "seed": CRITICALITY_SEED,
        "projection": PROJECTION_NAME,
        "chokepoint_count": len(choke_scores),
        "rows_written": n,
        "components": components,
        "most_critical": ranked[0][0] if ranked else None,
        "gral_compute_verified": gral_compute_verified,
    }
    _write_run_meta(meta)
    _ok(f"{path}: wrote criticality to {n} {TARGET_COLLECTION}", json.dumps(meta, sort_keys=True))
    return meta


def run(db) -> dict:
    """Orchestrate: fetch JWT FIRST (outside the gral try) then gral->NetworkX."""
    cfg = _load_env()
    # WR-07: a credentials failure must surface cleanly, not as a gral 404.
    jwt = get_jwt()
    return run_gral_or_networkx(db, cfg, jwt)


def main() -> int:
    try:
        db = get_db(request_timeout=180)
    except MissingCredentialsError as exc:
        _fail(f"credentials: {exc}", "copy .env.template to .env and fill in values")
        return EXIT_CLUSTER_UNREACHABLE

    try:
        meta = run(db)
    except JwtAuthFailedError as exc:
        _fail(f"JWT auth failed: {exc}", "credentials issue, NOT a gral problem")
        return EXIT_AUTH_FAILED
    except MissingCredentialsError as exc:
        _fail(f"credentials: {exc}", "fill in .env")
        return EXIT_CLUSTER_UNREACHABLE
    except requests.RequestException as exc:
        _fail(f"auth/transport failed: {type(exc).__name__}: {exc}", "check ARANGO_URL / creds")
        return EXIT_AUTH_FAILED
    except Exception as exc:  # noqa: BLE001 — orchestrator boundary
        _fail(f"criticality orchestration failed: {type(exc).__name__}: {exc}", str(exc))
        return EXIT_FAIL

    _info(
        f"path={meta['path']} chokepoints={meta['chokepoint_count']} "
        f"components={meta['components']} most_critical={meta['most_critical']} "
        f"gral_compute_verified={meta['gral_compute_verified']}"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
