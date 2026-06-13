# M2 Deck Source — Star over Snowflake (MOD-05)

> **Manual step:** This file is the repo-side source of truth. Placing this content onto the M2 "Star over Snowflake" slide in the shared Google Slides deck is a manual copy-paste step — do not create a new deck.

This defends the **locked** decision (MOD-05; PROJECT.md / CLAUDE.md) to model the warehouse as a flat **star** rather than a normalized **snowflake**. It is a defense of an already-made choice, not a re-opening of it.

## The defense (BigQuery columnar economics)

BigQuery is a serverless **columnar MPP** engine. Storage is cheap, and a query scans only the columns it touches — **unused columns are pruned for free** — so wide flat dimensions cost nothing for queries that don't read them. **Joins, by contrast, require data coordination across slots (communication bandwidth)** and are comparatively expensive. Snowflaking normalizes dimensions to *save storage* — row-store / OLTP-era reasoning that does not pay off on a columnar engine where storage is already cheap and columns prune for free; it only adds join cost and query complexity. Google's own guidance goes further than star, **recommending denormalization (nested/repeated fields)** for analytics; we keep flat star dimensions as the more *legible* middle ground for a course deliverable while staying BigQuery-idiomatic. None of the ocean-freight dimensions (`dim_port`, `dim_vessel`, `dim_carrier`, `dim_lane`, `dim_commodity`) are large, shared, and slowly-changing in a way that would make snowflake redundancy costly enough to justify the join penalty.

## Supporting evidence

- **Google denormalization guidance (the anchor citation):** "BigQuery performs best when your data is denormalized … take advantage of nested and repeated fields." This *strengthens* the anti-snowflake case — Google recommends going even flatter than a star, so a star sits comfortably on the denormalized side of the line.
- **Query-time cost of normalization:** on a columnar MPP engine the cost of normalization is paid at *query* time (extra joins), not saved at storage time — so denormalized/flat schemas measurably reduce query response time versus snowflaked ones. (We state this as a mechanism, not a single benchmark number; the magnitude is workload-dependent.)
- **Mechanism:** joins require data coordination (communication bandwidth) across slots, while denormalization localizes data to individual slots so execution runs in parallel — which is exactly why flat dimensions beat snowflaked ones on a columnar MPP engine.

---

*MOD-05 satisfied: star-over-snowflake defended on BigQuery columnar economics, anchored on Google denormalization guidance.*
