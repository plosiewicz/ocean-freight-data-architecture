# M2 Deck Source — Conformed-Key Bridge (MOD-07)

> **Manual step:** This file is the repo-side source of truth for the M2 "Conformed-Key Bridge" slide. Placing this content onto a slide in the shared Google Slides deck is a manual copy-paste step — do not create a new deck.
>
> **Team:** Grilled Cheesin · **Phase:** 2 (ER, Dimensional & Graph Design, M2) · **Requirement:** MOD-07

The conformed-key bridge is the **proof the hybrid is justified, not incidental.** The BigQuery star and the ArangoDB graph are not two disconnected databases — they share the **same deterministic natural keys**, so a result from one store joins cleanly back to the other. These keys are carried forward verbatim from Phase 1 (D-08/D-09/D-10) and the locked graph model (D-07); the deck *applies* them.

## The bridge table (MOD-07 / D-07 / Phase-1 D-08/D-09/D-10)

| Conformed entity | Natural key | BigQuery role | ArangoDB role |
|------------------|-------------|---------------|---------------|
| **Port** | **UN/LOCODE** | `dim_port.unlocode` — business key behind the `port_sk` surrogate | `ports/_key` = UN/LOCODE |
| **Vessel** | **IMO** (MMSI = AIS join key only) | `dim_vessel.imo` — business key behind `vessel_sk` | `vessels/_key` = IMO |
| **Carrier** | **SCAC** | `dim_carrier.scac` — business key behind `carrier_sk` | `carriers/_key` = SCAC |
| **Lane** | port-pair (origin + dest UN/LOCODE) | `dim_lane` (origin/dest UN/LOCODE business keys) | `route` / `segment` edge `_from` / `_to` (both are `ports/_key`) |

Each row is the **same conformed entity in two physical shapes**: a flat dimension row on the columnar warehouse, and a vertex (or edge) in the property graph — bound together by one shared natural key.

## The proof (the "hybrid is justified, not incidental" thesis)

Because the same deterministic natural key is **simultaneously the BigQuery dimension business key and the ArangoDB `_key`**, a graph pathfinding result — a sequence of port `_key`s returned by a weighted `SHORTEST_PATH` (UC4) or a reachability traversal (UC3) — joins **1:1** back to warehouse facts and dimensions **with no fuzzy matching**. A path that returns `["USHOU", "PACTB", "CNSHA"]` is directly a list of `dim_port.unlocode` business keys; no name-matching, geocoding, or probabilistic linkage is needed to pull the corresponding `fact_voyage_leg` rows or port dimension attributes.

That clean 1:1 join-back is **exactly what makes the two-store hybrid coherent** rather than two databases that happen to describe the same domain. It is why "the right store per workload" is a defensible architecture and not an incidental pairing: the graph answers the network questions, the warehouse answers the OLAP questions, and the shared natural keys let an answer from one immediately enrich an answer from the other.

## Featured example — one conformed entity, two physical shapes (Lane)

The **`dim_lane` ↔ graph `route`/`segment`** pair is the clearest single illustration of the bridge. A *lane* is one conformed entity. In the warehouse it is a **`dim_lane` row** (a flat dimension keyed by its origin+dest UN/LOCODE business key, joined from `fact_voyage_leg`/`fact_booking`). In the graph it is a **`route`/`segment` edge** whose `_from`/`_to` are the two port `_key`s (also UN/LOCODE). Same entity, same natural keys, two shapes optimized for two workloads — the dimensional measure-rollup view and the network-traversal view — with no key translation between them.

## Honesty note — IMO ↔ MMSI resolution is Phase 4, not solved here

This document states only the key **choice**: **IMO** is the vessel natural key (and Arango `vessels/_key`); **MMSI** is the AIS join key used at ingest. **How** an AIS MMSI resolves to the IMO natural key — the IMO↔MMSI resolution rules and collision handling — is a **Phase-4 (Silver conformance) risk**, flagged as highest-risk and **not designed or solved here**. The bridge above commits to the conformed-key *strategy*; it does not claim the resolution is already implemented.

---

*MOD-07 satisfied: UN/LOCODE / IMO / SCAC documented as the shared natural keys bridging the BigQuery star and the ArangoDB graph; 1:1 join-back is what makes the hybrid coherent.*
