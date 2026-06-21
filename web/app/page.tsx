import { UcCard } from "@/components/uc-card";
import { STORE_GROUPS, useCasesByStore } from "@/lib/use-cases";

// Landing / overview shell (APP-01). Leads with the right-store-per-workload
// thesis, then renders the four use-case cards split into the two store groups:
// OLAP/dimensional on BigQuery (UC1/UC2) vs network/graph on ArangoDB (UC3/UC4).

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <header className="mb-12 max-w-3xl">
        <p className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Ocean Freight Forwarder · Data Architecture
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          The right store per workload
        </h1>
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          A hybrid analytical architecture for global ocean container logistics.
          OLAP and dimensional questions — schedule reliability, port congestion —
          are answered on a defended <strong>BigQuery</strong> star schema. Network
          and relationship questions — chokepoint reachability, disruption
          rerouting — are answered on the <strong>ArangoDB</strong> property graph.
          Each use case below is tagged with the store that answers it.
        </p>
      </header>

      <div className="space-y-12">
        {STORE_GROUPS.map((group) => (
          <section key={group.store} aria-labelledby={`store-${group.store}`}>
            <div className="mb-4 flex items-baseline gap-3">
              <h2
                id={`store-${group.store}`}
                className="text-xl font-semibold tracking-tight"
              >
                {group.store}
              </h2>
              <span className="text-sm text-muted-foreground">
                {group.tagline}
              </span>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {useCasesByStore(group.store).map((uc) => (
                <UcCard key={uc.id} uc={uc} />
              ))}
            </div>
          </section>
        ))}
      </div>

      <footer className="mt-16 border-t pt-6 text-sm text-muted-foreground">
        MSDS 683 · Hybrid BigQuery + ArangoDB · overview skeleton (Phase 8). Live
        views land in Phase 9+.
      </footer>
    </main>
  );
}
