# M2 Deck Source — Data-Needs vs Sources Gap Analysis (MOD-08)

> **Manual step:** This file is the repo-side source of truth. Placing this content onto the M2 "Gap Analysis" slide in the shared Google Slides deck is a manual copy-paste step — do not create a new deck.
>
> **Team:** Grilled Cheesin · **Phase:** 2 (ER, Dimensional & Graph Design, M2) · **Requirement:** MOD-08

The honesty artifact for the M2 model. Every fact **measure**, dimension **attribute**, and graph **edge weight** in the design (four facts, six conformed dimensions, four lane-edge weights) is reconciled below against the data that supplies it, classified into the locked **three-tier real / prior / synthetic** strategy (`m1-real-vs-synthetic.md`, D-15), and — where the real data cannot supply it — its **gap** is named and its **mitigation** stated. Nothing here re-decides the model; it traces the already-locked model back to source so a reviewer can see that every value is grounded, conditioned, or honestly synthetic, and that the two structural gaps (the LSCI bilateral-port-pair gap and the chokepoint/AIS gap) are **defended design choices, not glossed-over holes**.

## Per-Attribute Reconciliation (D-12)

| Data need (attribute) | Used by | Source | Tier (real / prior / synthetic) | Gap | Mitigation |
|-----------------------|---------|--------|---------------------------------|-----|------------|
| `transit_hours` (`fact_voyage_leg`) | UC1 ETA reliability; graph `transit_time_hours` weight | AIS-derived leg durations (depart A → arrive B) | real | — | — |
| `distance_nm` (`fact_voyage_leg`) | UC1; graph `distance_nm` weight | AIS track + WPI port coordinates (great-circle / routed) | real | — | — |
| `schedule_delta_hours` (`fact_voyage_leg`) | UC1 delay driver | AIS arrival vs **synthetic proforma schedule** | real ↔ synthetic | No real proforma schedule for the bounded slice | Delta computed against deterministically-generated proforma; provenance flag distinguishes the synthetic baseline |
| `provenance` flag (all facts) | demo honesty; Phase-4 success criterion | row-stamped at landing | real / synthetic | — | Every row carries `real \| synthetic` from landing through Silver to demo (D-14) |
| `dwell_hours` (`fact_port_call`) | UC2 congestion / dwell | AIS-derived arrival → departure at a port | real | — | — |
| `turnaround_hours` (`fact_port_call`) | UC2 | AIS-derived port-call span | real | — | — |
| `anchorage_queue_hours` (`fact_port_call`) | UC2 congestion | AIS position dwell outside berth (geofenced anchorage) | real | AIS-derived anchorage geofencing is a Phase-4 derivation risk | Geofence rules over bounded AIS slice; flagged as highest-risk derivation in STATE.md (Phase 4), not claimed solved here |
| `booked_teu` / `declared_weight_kg` / `freight_amount` (`fact_booking`) | forwarder-internal transactional story | scaled synthetic generation | synthetic (designed now) | No public container-grain booking data (forwarder-internal) | Deterministic seeded generators; volume scaled to observed real AIS port-call count (D-12 scale grounding) |
| `event_type` / `event_sequence` / `hours_since_prior_event` (`fact_container_event`) | finest-grain event stream | synthetic generation off `fact_booking` | synthetic (designed now) | No public container status-event feed | Rule-based event lifecycle (gate-in → loaded → discharged → gate-out) over synthetic bookings |
| `imo` + `name` / `flag_state` (`dim_vessel`, SCD2) | UC1; conformed vessel key | AIS static (Type-5) + vessel reference | real | IMO present-but-sparse in unfiltered AIS; IMO↔MMSI resolution unsolved | Cargo/tanker filter raises IMO coverage to ~98.5%; MMSI is the AIS join key, IMO the conformed natural key; resolution deferred to Phase 4 |
| `scac` + `name` / `alliance` (`dim_carrier`, SCD2) | UC1; `operates` graph edge | reference-assigned | synthetic | **AIS carries no operator field** | Assign ~10–15 SCAC-keyed carriers synthetically; alliance/rebrand changes drive the SCD2 narrative |
| `unlocode` + `name` / `latitude` / `longitude` / `country` (`dim_port`, SCD1) | UC2, UC3, UC4; conformed port key | World Port Index (NGA Pub 150) | real | — (A3 resolved — WPI carries UN/LOCODE directly, col 6) | — |
| `lane_key` / `origin_unlocode` / `dest_unlocode` (`dim_lane`, SCD1) | UC4; `route`/`segment` edge endpoints | port-pair derived from conformed UN/LOCODE | real ↔ synthetic | No free port-pair route table exists | Lane structure derived/conditioned, not pulled from a feed — see note (a) |
| `hs_code` + `description` (`dim_commodity`, SCD1) | `fact_booking` commodity slice | UN Comtrade HS-code taxonomy assigned to synthetic bookings | prior → synthetic | No container-grain real commodity data | HS-code taxonomy (prior) provides the legal classification; assignment to bookings is synthetic |
| `full_date` / `year` / `quarter` / `month` / `day_of_week` (`dim_date`) | all temporal joins (UC1, UC2) | generated calendar | real (deterministic) | — | Static immutable dimension generated once |
| `transit_time_hours` (lane edge weight) | UC4 weighted `SHORTEST_PATH` primary cost | AIS-derived leg durations | real | — | — |
| `distance_nm` (lane edge weight) | UC4 secondary cost; reporting | geographic / WPI port coordinates | real | — | — |
| `service_frequency` (lane edge weight) | UC4 routing plausibility | Port-LSCI + UN Comtrade O-D | prior | **No free port-pair liner-service feed (LSCI is country-level only)** | Derive edge plausibility from Port-LSCI (per-port connectivity) × Comtrade O-D (per-lane demand) as conditioner-not-fact — see note (a) |
| `reliability_score` / `expected_delay` (lane edge weight) | UC1 ↔ UC4 shared reliability signal | World Bank LPI priors | prior | No lane-grain real reliability index | Condition lane reliability on country-level LPI; shared with UC1 so both stores reference one signal |
| `operates` (carrier → vessel edge) | `dim_carrier`; graph network | reference-assigned | synthetic | **AIS carries no operator field** | ~10–15 SCAC-keyed carriers assigned synthetically; documented |
| `calls_at` (vessel → port edge) | graph network structure | AIS-derived aggregate calls | real | — | Aggregated structural edge (D-07), not per-call |
| `route` / `segment` (port → port edge existence) | UC4 network shape | conditioned synthetic lane network | synthetic | No free port-pair route feed | Plausibility conditioned on Port-LSCI × Comtrade O-D priors — see note (a) |
| `transits_chokepoint` (lane → chokepoint edge) | UC3 chokepoint exposure | geographic routing rules over synthetic lanes | synthetic (rule-based) | **Real US-coastal AIS cannot observe Suez / Panama / Malacca** | Rule-based assignment over the synthetic lane network conditioned on real priors — see note (b) |

## Notes

### (a) LSCI bilateral-port-pair gap — a defended design choice, not a gap

There is **no free bilateral port-pair liner-service feed**. UNCTAD LSCI is published at **country-level** and per-port (Port-LSCI, >900 ports), not as a port-pair route table — a port-pair route+frequency feed is **proprietary** (e.g. Alphaliner / MDS). D-13 wants "which port-pairs carry liner service + at what frequency," which no free source supplies directly.

This is a **defended design choice, not a blocker**: per D-13 / D-15 the real indices are used as **priors / conditioners, never as facts**. Port-pair plausibility and the `service_frequency` / `route`/`segment` edge weights are **DERIVED** by combining **Port-LSCI** (per-port connectivity weight) with **UN Comtrade O-D** (per-lane demand weight) to condition the synthetic edges. If a reviewer asks "where is your route table?", the answer is that there isn't a free one — the synthetic network is conditioned by real per-port and per-lane priors, which is precisely the point of the real ↔ synthetic split (`m1-real-vs-synthetic.md` lines 40–44; `m1-source-inventory.md` note (d)).

### (b) Chokepoint / AIS gap — bounded US-coastal AIS cannot observe global chokepoints

The bounded real AIS slice is **US-coastal** (LA/Long Beach, NY/NJ, Savannah, Houston — D-04). By construction it **never observes** vessels transiting Suez, Panama, Malacca, or the other curated chokepoint nodes (Gibraltar, Bab-el-Mandeb, Hormuz, Cape of Good Hope, D-09). Therefore the `transits_chokepoint` edges (lane → chokepoint) **cannot be AIS-derived**.

This is stated plainly as a **defended design choice, not a hidden gap**: the chokepoint vertices are a curated fixed set, and `transits_chokepoint` edges are **assigned by geographic routing rules over the synthetic lane network**, conditioned on the real priors. UC3 (chokepoint risk exposure) is answered by AQL traversal/reachability over this honestly-synthetic structure — the bounded real AIS feed grounds transit times and dwell, while the global chokepoint topology is rule-based. Documenting this is what keeps the graph design defensible rather than overclaiming a global-observability the data does not have (D-09).

---

*MOD-08 satisfied: every fact measure / dim attribute / graph weight mapped to source + tier; LSCI bilateral gap and chokepoint-honesty point named and mitigated.*
