// Single source of truth for the four freight-forwarder use cases.
// Each UC is tagged with the store that answers it — the right-store-per-workload
// thesis the landing page leads with: OLAP/dimensional questions on the BigQuery
// star schema (UC1/UC2), network/relationship questions on the ArangoDB graph
// (UC3/UC4). Phase 9 fills in the live views behind each /uc<n> route.

export type Store = "BigQuery" | "ArangoDB";

export type Workload = "OLAP / dimensional" | "Graph / network";

export interface UseCase {
  id: "uc1" | "uc2" | "uc3" | "uc4";
  title: string;
  store: Store;
  workload: Workload;
  summary: string;
  href: string;
}

export const USE_CASES: UseCase[] = [
  {
    id: "uc1",
    title: "ETA reliability & delay drivers",
    store: "BigQuery",
    workload: "OLAP / dimensional",
    summary:
      "Which routes, carriers, and ports have the worst schedule reliability — and what drives the delay.",
    href: "/uc1",
  },
  {
    id: "uc2",
    title: "Port dwell & turnaround trend",
    store: "BigQuery",
    workload: "OLAP / dimensional",
    summary:
      "How congestion and dwell time at key ports trend over time and ripple downstream.",
    href: "/uc2",
  },
  {
    id: "uc3",
    title: "Chokepoint risk exposure",
    store: "ArangoDB",
    workload: "Graph / network",
    summary:
      "What share of shipments transit Suez / Panama / Malacca, and the reachability impact of a closure.",
    href: "/uc3",
  },
  {
    id: "uc4",
    title: "Disruption rerouting",
    store: "ArangoDB",
    workload: "Graph / network",
    summary:
      "The detour path and added transit-time delta when a chokepoint closes — shortest viable reroute.",
    href: "/uc4",
  },
];

export const STORE_GROUPS: { store: Store; tagline: string; ids: UseCase["id"][] }[] = [
  {
    store: "BigQuery",
    tagline: "OLAP / dimensional — star schema",
    ids: ["uc1", "uc2"],
  },
  {
    store: "ArangoDB",
    tagline: "Graph / network — property graph",
    ids: ["uc3", "uc4"],
  },
];

export function useCasesByStore(store: Store): UseCase[] {
  return USE_CASES.filter((uc) => uc.store === store);
}
