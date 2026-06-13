# Ocean Freight Forwarder Data Architecture (MSDS 683)

> Working codename: TBD · Team name (must be a food item per rubric): TBD · Members: TBD — finalize in M1.

## What This Is

An end-to-end data architecture for a **freight forwarder / 3PL** operating in **global ocean container logistics**. Multi-source, multi-format maritime data (real AIS vessel tracking + port reference + trade-flow data, augmented with synthetic bookings and container events) flows through a GCP pipeline into a **hybrid analytical layer**: a BigQuery star-schema warehouse for OLAP/dimensional analytics and an ArangoDB property graph for network/relationship analytics.

This is the group deliverable for **MSDS 683 (Data Architecture)** — graded on translating a domain into a data model, making and *defending* schema design decisions, implementing at least one cloud ETL process, orchestrating with Airflow, and demoing it. It is also intended as the design foundation for the **MSDS 681 (Data Lakehouse)** build next term.

## Core Value

The architecture must answer the four freight-forwarder analytical questions through the **right store per workload** — OLAP questions on a defended BigQuery star schema, network questions on the ArangoDB graph — proving that the hybrid design is justified rather than incidental.

## Requirements

### Validated

(None yet — ship to validate)

### Active

<!-- All hypotheses until shipped/demoed. Detailed, ID'd requirements live in REQUIREMENTS.md. -->

- [ ] Identify and document data sources (real + synthetic) and lock the domain — **M1 deliverable**
- [ ] Produce an ER diagram with 5–6+ entities and relationship annotations; reconcile data needs against sources; initial fact-vs-dimension classification — **M2 deliverable**
- [ ] Multi-source, multi-format ingestion landing in GCS (real AIS + port reference + trade flows + synthetic bookings/container events)
- [ ] At least one cloud ETL process implemented (GCS → transform → load)
- [ ] Airflow orchestration of the pipeline via Cloud Composer
- [ ] BigQuery **star-schema** dimensional warehouse serving the two OLAP use cases (ETA reliability, port congestion/dwell)
- [ ] ArangoDB property graph serving the two network use cases (chokepoint exposure, disruption rerouting)
- [ ] Working demo answering the four analytical use cases
- [ ] GitHub repo + access checklist — **M4 deliverable**

### Out of Scope

- **Snowflake schema (default)** — star is the recommended pattern for BigQuery's columnar engine; snowflake only if a specific dimension presents a compelling reason. (Decision recorded below.)
- **Real-time / streaming ingestion** — batch ETL is sufficient for v1; streaming adds operational complexity without serving the analytical use cases.
- **Heavy transform frameworks (Dataflow / dbt)** — deferred; keep the stack lean (Composer + BigQuery SQL) unless transform complexity demands it.
- **Full production governance/security suite** — governance is *not* this project's primary rubric characteristic (we chose scale + multi-source + temporal). Basic GCP IAM only; no anonymization/audit/access-control deep dive.
- **Full implementation of all 4 use cases** — v1 is design-heavy + one implemented ETL slice + demo; remaining use cases are designed-and-queryable, not fully built.
- **Mobile/standalone product UI** — beyond the demo / graph visualizer.

## Context

- **Prior art (pattern reference, not the substrate):** `/Users/plosiewicz/Desktop/supply-chain` — the "Brambles Pallet Network Digital Twin," a synthetic CHEP-AU pallet-flow demo on ArangoDB (~30K vertices / ~700K edges, deterministic seeded generators, idempotent loaders, Makefile-driven verb scripts, ship-gate verification, Pregel PageRank, GraphSAGE/Adamic-Adar link prediction). This course project is a **fresh domain** (ocean freight, not pallets) but should reuse the *patterns*: deterministic synthetic generation, idempotent loaders, Make-target structure, and verification gates.
- **Author background:** SE/SA for ArangoDB — graph capabilities are a deliberate strength to showcase.
- **Cloud:** GCP suite with available credits (GCS, Cloud Composer, BigQuery).
- **Candidate real data sources:** AIS vessel movements (MarineCadastre.gov / Global Fishing Watch — easily 100GB+, deeply temporal), UNCTAD / World Bank port and Liner Shipping Connectivity data, UN Comtrade trade flows. Synthetic augmentation: bookings, container/shipment events, schedule data.
- **Lakehouse continuity:** design should extend cleanly to the MSDS 681 lakehouse next term.

## Constraints

- **Timeline**: Course milestones M1 → M2 → M3 (midterm pitch) → M4 (GitHub repo) → Final demo. **Front-load M1 + M2 (all design) as Phases 1–2, before any implementation.**
- **Team**: 3 students (names + food-themed team name finalized in M1).
- **Tech stack**: ArangoDB (graph store), GCP — GCS (raw landing) + Cloud Composer (managed Airflow) + BigQuery (star-schema warehouse).
- **Budget**: GCP credits — prefer managed services already covered; avoid runaway compute (e.g., bound AIS volume to a defensible slice).
- **Deliverable format**: single Google Slides deck across all milestones (do not create new decks); working demo for the final.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Hybrid BigQuery + ArangoDB | Right store per workload — OLAP/dimensional questions (ETA, congestion) on BigQuery; network questions (chokepoint reachability, rerouting pathfinding) on the graph. Makes the hybrid defensible, not incidental. | — Pending |
| **Star schema default over snowflake** | BigQuery is columnar: storage is cheap, joins are comparatively costly, unused columns are pruned for free. Snowflake's normalization-to-save-storage is row-store/OLTP-era thinking that doesn't pay off in OLAP-on-BigQuery. Snowflake a dimension only with a specific compelling reason. | — Pending |
| Real-seed + synthetic mix | Real AIS/port/trade data grounds the model and supplies scale + temporal richness; synthetic bookings/container events fill gaps the public data can't (forwarder-internal transactions) and give deterministic control. | — Pending |
| GCS + Composer + BigQuery + Arango stack | Uses GCP credits; Composer is the rubric-required managed Airflow; lean (no Dataflow/dbt) until transform complexity demands it. | — Pending |
| Design-heavy + 1 implemented ETL slice | Rubric weight is on the ER model, dimensional decisions, and defended schema arguments; one vertical ETL slice + demo satisfies the implementation requirement for a 3-person term project. | — Pending |
| Freight-forwarder / 3PL perspective | Richest cross-source analytical story — touches carriers, ports, lanes, and risk simultaneously; frames all four use cases coherently. | — Pending |

## Analytical Use Cases (v1)

1. **ETA reliability & delay drivers** (OLAP / star schema) — which routes/carriers/ports have the worst schedule reliability and what drives delays.
2. **Port congestion & dwell-time trends** (temporal OLAP) — how congestion/dwell at key ports trends over time and ripples downstream.
3. **Chokepoint risk exposure** (graph reachability) — what share of shipments transit Suez/Panama/Malacca and the impact of a closure.
4. **Disruption rerouting / network optimization** (graph pathfinding) — best alternative routing when a lane is disrupted.

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-13 after initialization*
