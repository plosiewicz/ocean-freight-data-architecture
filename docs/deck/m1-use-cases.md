# M1 Deck Source — Four Analytical Use Cases (DOM-02)

> **Manual step:** This file is the repo-side source of truth. Placing this content onto the M1 "Analytical Use Cases" slide in the shared Google Slides deck is a manual copy-paste step — do not create a new deck.

The four analytical use cases are carried forward verbatim from `PROJECT.md` and phrased here as analytical questions, each annotated with the store that answers it.

## UC1 — ETA reliability & delay drivers (OLAP / star schema → BigQuery)

**Which routes, carriers, and ports have the worst schedule reliability, and what drives the delays?**

## UC2 — Port congestion & dwell-time trends (temporal OLAP → BigQuery)

**How do congestion and dwell time at key ports trend over time, and how do they ripple downstream?**

## UC3 — Chokepoint risk exposure (graph reachability → ArangoDB)

**What share of shipments transit Suez, Panama, or Malacca, and what is the impact of a closure?**

## UC4 — Disruption rerouting / network optimization (graph pathfinding → ArangoDB)

**What is the best alternative routing when a lane is disrupted?**

## Store-per-workload summary

- **BigQuery (star-schema OLAP):** UC1 (ETA reliability), UC2 (congestion / dwell trends).
- **ArangoDB (property graph):** UC3 (chokepoint reachability), UC4 (rerouting pathfinding).

This split is what makes the hybrid architecture defensible rather than incidental: the OLAP/dimensional questions live on the columnar warehouse, the network/relationship questions live on the graph.
