"""ETL-05 — cross-store (BigQuery <-> ArangoDB) reconciliation logic.

This module holds the PURE reconciliation helpers that the Wave-5
``scripts/verify.py`` graph gates (exit codes 17 / 18) call with LIVE count /
traversal providers, and that ``tests/test_cross_store.py`` exercises fully
OFFLINE with MOCKED providers. Keeping the comparison logic here (side-effect
free, no cluster / no BigQuery import) is what makes the ETL-05 reconciliation
contract unit-testable without credentials.

ETL-05 is the coherence proof of the hybrid architecture: the SAME conformed
Silver layer feeds BigQuery (the star) AND ArangoDB (the ocean_network graph),
and a shared deterministic business key (UN/LOCODE for ports, IMO for vessels,
SCAC for carriers, the ``lane_key`` for lanes — the D-11 bridge) lets a row in
one store reconcile 1:1 against the other. Two layers of reconciliation:

  1. COUNT PARITY (gate 17): for each conformed dim, the count of BigQuery rows
     (current rows only, for the SCD2 dims) equals the count of ArangoDB vertices
     in the corresponding collection. A mismatch means the shared-key bridge
     dropped or duplicated an entity between the two sinks.

  2. SEMANTIC (gate 18): a derived NETWORK metric — the number of lanes that
     transit the Suez chokepoint — reconciles between the two stores. The Suez
     lane set is defined by the deterministic geographic rule
     (``lib.graph_loader.chokepoints_for_lane``) over the canonical ``LANES``
     network; the ArangoDB side counts the ``transits_chokepoint -> SUEZ`` edges,
     and the count must equal the rule's count. The same ``lane_key`` bridge is
     reported against BigQuery ``dim_lane`` so the deck can cite the shared key.

Both helpers return ``(ok: bool, mismatches: list[str])`` so a gate can map a
non-empty mismatch list to its distinct exit code and PRINT each mismatch.

Provenance: 06-05-PLAN.md Task 1; 06-PATTERNS.md "scripts/verify.py (modify)" +
RESEARCH Code Example 6; lib.graph_loader.chokepoints_for_lane (the D-09 rule).
"""

from __future__ import annotations

from typing import Iterable

# The chokepoint whose transit-share is reconciled across the two stores (D-09:
# Suez is the featured demo chokepoint). Kept as a module constant so the gate and
# the offline test agree on the same target.
SUEZ_KEY: str = "SUEZ"


def check_count_parity(
    pairs: Iterable[tuple[str, int, str, int]],
) -> tuple[bool, list[str]]:
    """Reconcile BigQuery dim row counts against ArangoDB vertex counts.

    ``pairs`` is an iterable of ``(dim_name, bq_count, vertex_collection,
    arango_count)`` tuples. The shared-key bridge (D-11) makes every BigQuery
    dimension row correspond 1:1 to exactly one graph vertex, so the counts MUST
    be equal. Returns ``(ok, mismatches)`` where ``ok`` is ``True`` iff every pair
    matches and ``mismatches`` lists a human-readable line per mismatch (naming
    BOTH the dim and the vertex collection so the gate hint is actionable).

    Pure: the caller supplies already-fetched counts (live in the gate, mocked in
    the test), so this function never touches BigQuery or the cluster.
    """
    mismatches: list[str] = []
    for dim_name, bq_count, vertex_collection, arango_count in pairs:
        if bq_count != arango_count:
            mismatches.append(
                f"{dim_name}={bq_count} != {vertex_collection}={arango_count} "
                f"(shared-key bridge broken — UN/LOCODE/IMO/SCAC mismatch)"
            )
    return (not mismatches, mismatches)


def suez_lane_keys(
    lanes: Iterable[tuple[str, str]],
    rule,
) -> list[str]:
    """Return the canonical ``lane_key``s whose geographic rule transits Suez.

    ``lanes`` is the canonical directed port-pair network (``data_gen.network.LANES``);
    ``rule`` is the deterministic ``chokepoints_for_lane(origin, dest) -> tuple``
    (``lib.graph_loader.chokepoints_for_lane``). A lane transits Suez iff
    ``SUEZ_KEY`` is in its rule result. The returned keys use the same
    ``f"{origin}__{dest}"`` convention as ``lib.graph_loader.lane_key`` — the
    shared lane bridge across both stores. Order-stable (follows ``lanes`` order).
    """
    return [
        f"{origin}__{dest}"
        for (origin, dest) in lanes
        if SUEZ_KEY in rule(origin, dest)
    ]


def check_semantic_suez(
    expected_suez_lane_count: int,
    arango_suez_edge_count: int,
    bq_lane_key_overlap: int,
) -> tuple[bool, list[str]]:
    """Reconcile the Suez transit-share between ArangoDB and the canonical network.

    Three quantities, all derived from the SAME shared ``lane_key`` bridge:

      * ``expected_suez_lane_count`` — Suez-transiting lanes per the deterministic
        geographic rule over the canonical ``LANES`` network (the ground truth both
        stores are projected from).
      * ``arango_suez_edge_count`` — the live count of ``transits_chokepoint -> SUEZ``
        edges in the ocean_network graph (the graph-store realization of the rule).
      * ``bq_lane_key_overlap`` — how many of the canonical Suez ``lane_key``s also
        appear in BigQuery ``dim_lane`` (the warehouse-store realization; reported
        for the deck, may be < expected because real ``dim_lane`` holds only
        observed/served lanes — that gap is honest and not a failure on its own).

    The HARD reconciliation is ``arango_suez_edge_count == expected_suez_lane_count``
    (the graph projected exactly the rule's lanes — no edge dropped or duplicated).
    Returns ``(ok, mismatches)``.
    """
    mismatches: list[str] = []
    if arango_suez_edge_count != expected_suez_lane_count:
        mismatches.append(
            f"Suez transit edges: Arango transits_chokepoint->SUEZ="
            f"{arango_suez_edge_count} != rule-expected={expected_suez_lane_count} "
            f"(graph did not project exactly the geographic-rule Suez lanes)"
        )
    # bq_lane_key_overlap is reported (not hard-asserted): real dim_lane may hold a
    # subset of the synthetic network. A NEGATIVE overlap is impossible and would be
    # a logic error in the caller.
    if bq_lane_key_overlap < 0:
        mismatches.append(
            f"BQ lane_key overlap is negative ({bq_lane_key_overlap}) — caller bug"
        )
    return (not mismatches, mismatches)
