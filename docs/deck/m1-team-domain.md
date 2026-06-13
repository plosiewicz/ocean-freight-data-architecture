# M1 Deck Source — Team & Domain (DOM-01)

> **Manual step:** This file is the repo-side source of truth. Placing this content onto the M1 "Team & Domain" slide in the shared Google Slides deck is a manual copy-paste step — do not create a new deck.

## Team

- **Team name (food-themed, per rubric):** **Grilled Cheesin**
- **Members (3-person group):**
  - P.J. Losiewicz
  - Borna Karimi
  - Alexander Mohun

## Domain

An **end-to-end data architecture for a freight forwarder / 3PL operating in global ocean container logistics**. Real, multi-source maritime data (AIS vessel tracking + port reference + trade-flow priors) is augmented with synthetic bookings and container events, then flows through a GCP pipeline into a **hybrid analytical layer**.

**One-line framing:** A hybrid analytical layer — a **BigQuery star-schema warehouse** for OLAP / dimensional analytics and an **ArangoDB property graph** for network / relationship analytics — answering each freight-forwarder question on the right store per workload.

## Why this domain

The freight-forwarder / 3PL perspective gives the richest cross-source analytical story — it touches carriers, ports, lanes, and risk simultaneously — and frames all four analytical use cases coherently (see the four-use-cases slide). It also exercises scale, multi-source/multi-format ingestion, and temporal richness, the rubric axes this project chose to emphasize.
