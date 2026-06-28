# ArangoDB (graph store) + AQL / GAE

**Layer:** graph store — the `ocean_network` property graph that answers UC3 + UC4.

## What it does
ArangoDB is a multi-model database; we use its **native property graph**. A named graph
`ocean_network` holds 5 vertex collections (`ports`, `vessels`, `carriers`, `lanes`, `chokepoints`)
and 4 edge collections (`route`, `calls_at`, `operates`, `transits_chokepoint`). Queries are written
in **AQL**, including `K_SHORTEST_PATHS` weighted traversal; server-side centrality / PageRank /
connected-components run on the cluster's **Graph Analytics Engine (GAE)**.

## Role in our project
- Serves the **network use cases**: **UC3 chokepoint exposure / closure impact** and **UC4
  weighted-shortest-path rerouting** — "what's reachable if a node disappears" and "cheapest detour
  under disruption."
- Loaded by `lib/graph_loader.py` from the *same* Silver dims (idempotent `UPSERT`), with the
  synthetic priors-conditioned lane network and the four D-08 route-edge weights.
- **Conformed-key bridge:** every vertex `_key` equals the matching BigQuery business key
  (UN/LOCODE / IMO / SCAC), so a graph result joins 1:1 back to a warehouse fact — that's what makes
  the two stores *one* architecture.
- Queries live as versioned `aql/uc3_*.aql` / `aql/uc4_*.aql` with committed `.explain` plans.

## Why it's the best option here
- **The workload is genuinely graph-shaped.** UC3/UC4 are reachability and weighted shortest-path
  under node removal — natural as a named-graph traversal + `K_SHORTEST_PATHS`, painful and
  unreadable as recursive SQL CTEs. This is the concrete justification for the *hybrid* design.
- **Team expertise / managed cluster.** The author is an ArangoDB SE; the team has a managed
  ArangoDB cloud cluster (credentials provided) that exposes GAE/GraphML server-side. Lowest-risk,
  highest-fluency choice for us.
- **Multi-model + deterministic keys.** Source-derived `_key`s (UN/LOCODE, IMO, SCAC) make loads
  idempotent and edges resolve `_from`/`_to` reliably — the same keys bridge to BigQuery.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| Neo4j | Strong graph DB, but Cypher-only, separate licensing, and not where our expertise/managed cluster is | A Cypher/Neo4j shop |
| Recursive SQL CTEs in BigQuery | Shortest-path-under-closure is degenerate and unreadable in SQL; no native weighted pathfinding | Trivial 1–2 hop reachability only |
| NetworkX / nx-arangodb (client-side) | Kept as the **fallback** for centrality, but server-side GAE on the cluster is the primary path at our scale | No server-side engine available; small graphs |
| ArangoDB Pregel | **Removed in 3.12** — the old PageRank pattern won't run | n/a — replaced by GAE |
| A graph Web-UI visualizer in the demo | Out of scope by design — we demo the back-end DB + native algorithms, returned programmatically (parallel to the SQL half) | A purely visual storytelling demo |

## Likely Q&A
- *"Why not just do this in SQL?"* — UC3/UC4 are node-removal reachability and weighted shortest-path;
  graph traversal expresses them directly, recursive CTEs do not.
- *"Why `K_SHORTEST_PATHS` not `SHORTEST_PATH`?"* — a bare shortest-path filters disabled lanes *after*
  finding the optimum, so closing the best lane returns empty. K-shortest enumerates by increasing
  weight; we keep the cheapest path that avoids the closed chokepoint → a genuine, positive-delta detour.
- *"What about Pregel?"* — removed in ArangoDB 3.12; we use AQL traversal for pathfinding and the
  cluster's GAE for centrality, with NetworkX as a documented fallback.
