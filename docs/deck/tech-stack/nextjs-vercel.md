# Next.js + deck.gl + Vercel (the end product)

**Layer:** the consumable output — the dashboard the brief now requires the demo to end in.

## What it does
- **Next.js 16** (React, App Router) — the web app framework; server components fetch Gold data, client
  components render it.
- **deck.gl + MapLibre / react-map-gl** — WebGL map layers for the chokepoint/route/reroute geospatial
  views (UC3/UC4); **recharts** for the UC1/UC2 trend charts; **shadcn/Radix + Tailwind** for the UI.
- **`@google-cloud/bigquery` + `arangojs`** — read **live** from the two Gold stores, with frozen-golden
  fallback when no credentials are present.
- **Vercel** — zero-config hosting/deploy for the Next.js app.

## Role in our project
- `web/app/uc{1..4}/page.tsx`: four pages — UC1/UC2 as KPI tables + trend charts off BigQuery;
  UC3/UC4 as an interactive map showing transit share and the live reroute path on chokepoint closure.
- This **is** the brief's "concrete, consumable output": the pipeline output lands as a dashboard a
  non-technical planner reads ("closing Suez adds +76 h to NYC→Shanghai, rerouting via LA"), not rows
  in a database.
- **Failure-proof demo:** server fetchers are credential-gated and fall back to the committed
  `data/golden/uc*.golden.json`, so the app renders top-to-bottom from a clean clone; a recorded
  backup exists as the can't-fail fallback.

## Why it's the best option here
- **It satisfies the new brief directly** — "end product should be something a non-technical domain
  user can look at and get value from"; an interactive map + charts is exactly that.
- **deck.gl is purpose-built for geospatial** route/chokepoint rendering — the domain is literally a
  map, so a WebGL map layer beats a generic chart grid for UC3/UC4.
- **Next.js server components let the app read Gold directly** (BigQuery + ArangoDB) with a clean
  golden fallback, so the demo is both *live-capable* and *can't-fail*.
- **Vercel** is zero-ops hosting — no server to run, instant preview URLs, matches the managed-first
  stack philosophy.

## Alternatives considered
| Alternative | Why not here | When you'd pick it |
|---|---|---|
| Looker Studio / a BI tool | Fast for charts, but weak for custom interactive geospatial reroute viz, and less of a built artifact | Pure tabular BI dashboards |
| Jupyter notebook only | We keep `docs/demo.ipynb` as a backup, but a notebook isn't the "non-technical consumable" the brief now asks for | Technical walkthroughs |
| A bare static map / screenshots | No interactivity (can't toggle a closure live) | A purely narrated slide |
| Self-hosted Node server | Operational overhead vs. Vercel's zero-config deploy | When platform constraints forbid Vercel |
| Streamlit / Dash | Fine Python dashboards, but deck.gl + Next.js gives better geospatial control and a real deployable app | Quick Python-only internal tools |

## Likely Q&A
- *"Is the dashboard live or canned?"* — both: it reads live BigQuery/ArangoDB when credentialed, and
  falls back to frozen goldens otherwise, so it can't fail on stage but proves out live on demand.
- *"Why a custom app instead of a BI tool?"* — UC3/UC4 need interactive geospatial reroute
  visualization (toggle a chokepoint closed, watch the path re-route) that a generic BI tool doesn't do well.
