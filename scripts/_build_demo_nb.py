"""One-shot builder for docs/demo.ipynb (DEL-01, Phase 07-03).

Emits the four-use-case failure-proof demo notebook as a valid nbformat-4 JSON.
The notebook's DEFAULT path reads the committed data/golden/uc*.golden.json
snapshots (zero credentials, no network) so the demo cannot fail live; an
OPTIONAL live-path aside (guarded by LIVE=False) is the only cluster/BQ touch.

This builder is a dev convenience, NOT committed as the demo surface — the
committed artifact is docs/demo.ipynb itself. Run:  python scripts/_build_demo_nb.py
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

REPO_ROOT = Path(__file__).resolve().parent.parent
NB_PATH = REPO_ROOT / "docs" / "demo.ipynb"

nb = nbf.v4.new_notebook()
cells: list = []


def md(src: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(src.strip("\n")))


def code(src: str) -> None:
    cells.append(nbf.v4.new_code_cell(src.strip("\n")))


# ------------------------------------------------------------------ Title + thesis
md(
    """
# Ocean Freight Forwarder — Four-Use-Case Demo

**Team Grilled Cheesin** · P.J. Losiewicz · Borna Karimi · Alexander Mohun · MSDS 683 (Data Architecture)

## Thesis: the right store per workload

The four freight-forwarder analytical questions **do not all want the same kind of
database**. OLAP roll-ups ("which carrier is most reliable", "how does dwell trend")
live on a columnar warehouse; network questions ("what becomes unreachable if Suez
closes", "what's the best reroute") are about *paths and connections*, not aggregates.
So the architecture is a **hybrid analytical layer** — a defended **BigQuery star
schema** for the OLAP questions and an **ArangoDB property graph** for the network
questions. The point is that the hybrid is *justified*, not incidental.

| # | Analytical question | Store |
|---|---------------------|-------|
| **UC1** | Which routes, carriers, and ports have the worst schedule reliability, and what drives the delays? | **BigQuery** (OLAP / star) |
| **UC2** | How do congestion and dwell time at key ports trend over time? | **BigQuery** (temporal OLAP) |
| **UC3** | What share of shipments transit Suez/Panama/Malacca, and what's the impact of a closure? | **ArangoDB** (graph reachability) |
| **UC4** | What is the best alternative routing when a lane is disrupted? | **ArangoDB** (graph pathfinding) |

> **Failure-proof by design.** Every section below reads a **pre-computed, frozen
> snapshot** committed under `data/golden/uc*.golden.json` — so this notebook runs
> top-to-bottom **from a fresh clone with no credentials** and cannot fail live. The
> snapshots were frozen from the live BigQuery warehouse (UC1/UC2) and the managed
> ArangoDB cluster (UC3/UC4) via `make freeze`. A single **optional "look, it's real"
> aside** at the very end can re-run the graph use cases against the live cluster — it
> is guarded off (`LIVE = False`) and is never required for the demo to render.
"""
)

# ------------------------------------------------------------------ shared loader
code(
    '''
"""Shared golden-snapshot loader (the failure-proof default path).

Resolves data/golden/ relative to the repo root so the notebook runs from a fresh
clone regardless of the kernel's working directory. Reads committed JSON only — no
network, no credentials.
"""
import json
from pathlib import Path


def _repo_root() -> Path:
    """Walk up from CWD until we find the committed data/golden/ snapshots."""
    here = Path.cwd().resolve()
    for cand in (here, *here.parents):
        if (cand / "data" / "golden" / "uc1.golden.json").exists():
            return cand
    raise FileNotFoundError(
        "data/golden/uc*.golden.json not found — run this notebook from inside the repo "
        "(the frozen snapshots are committed; `make freeze` regenerates them)."
    )


REPO_ROOT = _repo_root()
GOLDEN_DIR = REPO_ROOT / "data" / "golden"


def load_golden(uc: str) -> dict:
    """Load a frozen UC snapshot, e.g. load_golden('uc3')."""
    return json.loads((GOLDEN_DIR / f"{uc}.golden.json").read_text())


print(f"Reading frozen snapshots from: {GOLDEN_DIR}")
print("Default path: zero credentials, no network — committed goldens only.")
'''
)

# ------------------------------------------------------------------ UC1
md(
    """
## UC1 — ETA reliability  ·  *BigQuery (OLAP / star)*

**Question:** which routes, carriers, and ports have the worst schedule reliability,
and what drives the delays? This is a classic OLAP roll-up — group by carrier × lane,
average the schedule delta, compare on-time %. It runs on the **BigQuery star schema**
(`fact_voyage_leg` joined to `dim_carrier` / `dim_lane`), the versioned query
`sql/uc1_eta_reliability.sql`.
"""
)
code(
    '''
uc1 = load_golden("uc1")
print(f"Store: {uc1['store']}  ·  query: {uc1['query']}  ·  {uc1['row_count']} carrier/lane rows")

# Worst-reliability carrier/lane groups: sort by on-time %, then by avg delay (worst first).
rows = sorted(uc1["rows"], key=lambda r: (r["on_time_pct"], -r["avg_delay_hours"]))
print(f"\\n{'carrier':<16}{'lane':<14}{'legs':>5}{'on_time_%':>11}{'avg_delay_h':>13}")
print("-" * 59)
for r in rows[:8]:
    print(
        f"{r['carrier_name']:<16}{r['lane_key']:<14}{r['legs']:>5}"
        f"{r['on_time_pct']:>11.1f}{r['avg_delay_hours']:>13.2f}"
    )
print("\\nReading: the worst on-time lanes/carriers surface first — the OLAP roll-up "
      "answers 'who is least reliable, and by how much'.")
'''
)

# ------------------------------------------------------------------ UC2
md(
    """
## UC2 — Port congestion / dwell trend  ·  *BigQuery (temporal OLAP)*

**Question:** how do congestion and dwell time at key ports trend over time? A temporal
OLAP aggregation — average turnaround per port per day, trended across the slice. Runs
on `fact_port_call` via `sql/uc2_dwell_trend.sql`, exercising the warehouse's
**date-partitioned** layout.
"""
)
code(
    '''
uc2 = load_golden("uc2")
print(f"Store: {uc2['store']}  ·  query: {uc2['query']}  ·  "
      f"{uc2['row_count']} port-day rows across {uc2['distinct_call_dates']} dates")

# Roll the port-day grain up to a per-port summary (mean / peak turnaround across the slice).
from collections import defaultdict

agg: dict[str, list[float]] = defaultdict(list)
peak: dict[str, float] = defaultdict(float)
for r in uc2["rows"]:
    agg[r["unlocode"]].append(r["avg_turnaround_hours"])
    peak[r["unlocode"]] = max(peak[r["unlocode"]], r["max_turnaround_hours"])

print(f"\\n{'port':<8}{'days':>6}{'mean_turnaround_h':>20}{'peak_turnaround_h':>20}")
print("-" * 54)
for port in sorted(agg):
    vals = agg[port]
    print(f"{port:<8}{len(vals):>6}{sum(vals) / len(vals):>20.2f}{peak[port]:>20.2f}")
print("\\nReading: USLAX carries the heaviest dwell — the temporal roll-up shows where "
      "congestion concentrates and how it trends day over day.")
'''
)

# ------------------------------------------------------------------ UC3
md(
    """
## UC3 — Chokepoint exposure & closure impact  ·  *ArangoDB (graph reachability)*

**Question:** what share of US-trade lanes transit Suez/Panama/Malacca, and what is the
impact of a closure? This is a **network** question — transit share is a subgraph join,
and a closure's impact is measured two ways on the `ocean_network` graph:

1. **Reroute impact** (Suez): close the Suez-transiting lanes and re-run the weighted
   `K_SHORTEST_PATHS` — the answer is the **added transit hours** (delta) on the detour.
2. **Genuine unreachability** (Gibraltar): closing Gibraltar *fragments* the graph —
   strictly fewer ports remain reachable.

Both numbers below are read **from the frozen golden**, not hard-coded.
"""
)
code(
    '''
uc3 = load_golden("uc3")
print(f"Store: graph (ArangoDB ocean_network)  ·  use_case: {uc3['use_case']}")

# (a) Chokepoint transit share across US-trade lanes.
print("\\nChokepoint transit share (US-trade lanes):")
print(f"{'chokepoint':<14}{'transiting':>11}{'of_total':>10}{'share_%':>10}")
print("-" * 45)
for c in sorted(uc3["transit_share"], key=lambda r: -r["transit_share_pct"]):
    print(f"{c['chokepoint']:<14}{c['transiting_lanes']:>11}{c['total_lanes']:>10}"
          f"{c['transit_share_pct']:>10.1f}")

# (b) Suez closure -> reroute impact (delta read from golden; non-degenerate => delta > 0).
ri = uc3["reroute_impact_suez"]
delta = ri["delta"]
print(f"\\nSUEZ closure reroute impact ({ri['origin']} -> {ri['dest']}):")
print(f"  baseline transit : {ri['baseline_hours']:.2f} h")
print(f"  reroute transit  : {ri['reroute_hours']:.2f} h")
print(f"  added delay (delta): +{delta:.2f} h   <- strictly positive (non-degenerate)")
assert delta > 0, "UC3 reroute delta must be strictly positive (non-degenerate)"

# (c) Gibraltar closure -> genuine reachability DROP (closed reachable < open reachable).
cg = uc3["closure_gibraltar"]
open_total, closed_total = cg["open_reachable_total"], cg["closed_reachable_total"]
print(f"\\nGIBRALTAR closure reachability drop (across {cg['open_origins']} origins):")
print(f"  reachable with strait OPEN  : {open_total}")
print(f"  reachable with strait CLOSED: {closed_total}   <- strictly fewer (graph fragments)")
assert closed_total < open_total, "UC3 Gibraltar closure must strictly reduce reachability"

print("\\nReading: the graph answers BOTH 'how much longer is the detour' (Suez, "
      f"+{delta:.1f}h) and 'what becomes unreachable' (Gibraltar, {open_total} -> {closed_total}) "
      "— neither is expressible as a warehouse roll-up.")
'''
)

# ------------------------------------------------------------------ UC4
md(
    """
## UC4 — Disruption rerouting  ·  *ArangoDB (graph pathfinding)*

**Question:** when a lane is disrupted, what is the best alternative routing? A weighted
shortest-path problem on `ocean_network` — disable the affected lanes and re-solve. The
golden carries the baseline path, the differing reroute path, and the added-hours delta.
"""
)
code(
    '''
uc4 = load_golden("uc4")
print(f"Store: graph (ArangoDB ocean_network)  ·  use_case: {uc4['use_case']}")
print(f"Route: {uc4['origin']} -> {uc4['dest']}  ·  {len(uc4['disabled_lanes'])} lanes disabled")


def fmt_path(path: list[dict]) -> str:
    return " -> ".join(f"{leg['port']}(+{leg['leg_hours']:.0f}h)" for leg in path)


print(f"\\n  baseline path : {fmt_path(uc4['baseline_path'])}   = {uc4['baseline_hours']:.2f} h")
print(f"  reroute path  : {fmt_path(uc4['reroute_path'])}   = {uc4['reroute_hours']:.2f} h")

baseline_ports = [leg["port"] for leg in uc4["baseline_path"]]
reroute_ports = [leg["port"] for leg in uc4["reroute_path"]]
assert reroute_ports != baseline_ports, "UC4 reroute path must differ from the baseline"

delta = uc4["delta"]
print(f"  added delay (delta): +{delta:.2f} h   <- strictly positive (non-degenerate)")
assert delta > 0, "UC4 reroute delta must be strictly positive (non-degenerate)"

print("\\nReading: the reroute detours via USLAX (a genuinely different path), at a "
      f"+{delta:.1f}h cost — pathfinding the warehouse cannot do.")
'''
)

# ------------------------------------------------------------------ optional live aside
md(
    """
## Optional aside — *"look, it's real"* (live cluster path, OFF by default)

Everything above ran from frozen snapshots with **no credentials**. The cell below is
the *only* code that would touch the live managed ArangoDB cluster — it is **guarded
off** (`LIVE = False`) and is **never required** for the demo to render. To run it, set
`LIVE = True` **and** provide the `ARANGO_*` credentials in a gitignored `.env`
(see `.env.template`). It delegates to `lib.arango_client.get_db` / the
`analytics.snapshot_uc` runners and prints results only — it never logs credentials.
"""
)
code(
    '''
LIVE = False  # <- leave False for the failure-proof demo; set True only with live .env creds

if LIVE:
    # Imported lazily so the default path needs neither the cluster nor python-arango.
    from analytics.snapshot_uc import snapshot_uc3, snapshot_uc4

    live3 = snapshot_uc3()
    live4 = snapshot_uc4()
    print("LIVE UC3 Suez reroute delta:", live3["reroute_impact_suez"]["delta"], "h")
    print("LIVE UC4 reroute delta     :", live4["delta"], "h")
    print("(These should match the frozen goldens above — same query, live cluster.)")
else:
    print("Live path is OFF (LIVE = False). The demo above ran entirely from frozen "
          "snapshots — no credentials, no network. Set LIVE = True with .env creds to "
          "hit the managed ArangoDB cluster directly.")
'''
)

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}

NB_PATH.write_text(nbf.writes(nb))
print(f"Wrote {NB_PATH}")
