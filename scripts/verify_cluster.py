"""Connection-smoke diagnostic for the managed ArangoDB cluster (`make verify-cluster`).

A FRONT-LOADED connection check the RESEARCH recommends running BEFORE the live
``make load-arango`` / ``make verify`` graph gates — it proves the gitignored
``.env`` credentials reach the managed cluster over TLS and prints a multi-key
diagnostic (ported from ``supply-chain/lib/arango_client.py::verify_cluster``).

Connects ONLY via :mod:`lib.arango_client` (env creds, TLS always on). It prints
the diagnostic keys and the current username, but NEVER the password or JWT
(threat T-06-01 / T-06-03). On missing/invalid credentials it exits non-zero with
the actionable ``MissingCredentialsError`` message (which names the missing vars
and points at ``.env``), so an env-var-name mismatch is diagnosed cleanly rather
than surfacing as an opaque connection error.

Exit codes: 0 = reachable; 1 = missing credentials; 2 = unreachable / other error.

Provenance: 06-05-PLAN.md Task 1 (verify-cluster smoke target);
06-PATTERNS.md "Optionally also port verify_cluster()";
supply-chain/lib/arango_client.py lines 150-219 (the 10-key diagnostic shape).
"""

from __future__ import annotations

import sys
from time import perf_counter

from lib.arango_client import MissingCredentialsError, arango_url, get_db


def verify_cluster() -> dict:
    """Return a diagnostic payload after a live, TLS-on round-trip to the cluster.

    Talks to the ``_system`` database for the version + cluster topology, and to the
    configured project database (``ARANGO_DATABASE``) to confirm it exists and report
    whether the ``ocean_network`` graph is already present. No credentials are placed
    in the returned payload.
    """
    # Project DB handle (the .env ARANGO_DATABASE) — also forces a live connection.
    db = get_db(request_timeout=60)

    t0 = perf_counter()
    arangodb_version = db.version()
    version_rtt_ms = round((perf_counter() - t0) * 1000.0, 1)

    coordinator_count = db_server_count = agent_count = 0
    cluster_mode = "single"
    try:
        health = db.cluster.health()
        entries = (health or {}).get("Health", health or {})
        if isinstance(entries, dict):
            for entry in entries.values():
                role = (entry or {}).get("Role", "")
                if role == "Coordinator":
                    coordinator_count += 1
                elif role == "DBServer":
                    db_server_count += 1
                elif role == "Agent":
                    agent_count += 1
        if coordinator_count >= 1:
            cluster_mode = "cluster"
    except Exception:  # noqa: BLE001 — single-server deployments expose no cluster API
        cluster_mode = "single"

    try:
        ocean_network_exists = db.has_graph("ocean_network")
    except Exception:  # noqa: BLE001 — best-effort
        ocean_network_exists = None

    try:
        collection_count = len([c for c in db.collections() if not c["name"].startswith("_")])
    except Exception:  # noqa: BLE001
        collection_count = None

    return {
        "arango_url": arango_url(),  # host only — never credentials
        "arangodb_version": arangodb_version,
        "cluster_mode": cluster_mode,
        "coordinator_count": coordinator_count,
        "db_server_count": db_server_count,
        "agent_count": agent_count,
        "database": db.name,
        "ocean_network_exists": ocean_network_exists,
        "user_collection_count": collection_count,
        "version_rtt_ms": version_rtt_ms,
    }


def main() -> int:
    try:
        diag = verify_cluster()
    except MissingCredentialsError as exc:
        print(f"[FAIL] verify-cluster: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(
            f"[FAIL] verify-cluster: managed cluster unreachable (check ARANGO_URL / TLS): {exc}",
            file=sys.stderr,
        )
        return 2

    print("[OK] managed ArangoDB cluster reachable (TLS-on) — connection-smoke diagnostic:")
    for key, value in diag.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
