import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  Uc4Envelope,
  Uc4PathHop,
  Uc4ReliabilitySidecar,
  Uc4RouteReliability,
} from "@/lib/golden-types";

// Render-only Server Component for /uc4 (Disruption rerouting, ArangoDB / graph).
// Renders the baseline vs reroute path hops (port + per-leg hours) and surfaces the
// +76.22h transit-time delta as a prominent callout (D-11 / CONTEXT specifics).
// Dependency-free — Card primitives only, NO shadcn table (Plan 03 owns that install).
// Persists as the textual companion under the Phase-10 reroute-arc map (no rework).

function PathColumn({
  label,
  hops,
  totalHours,
  emphasis,
}: {
  label: string;
  hops: Uc4PathHop[];
  totalHours: number;
  emphasis?: boolean;
}) {
  return (
    <div className="flex-1">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span
          className={
            emphasis
              ? "text-sm font-semibold tabular-nums text-destructive"
              : "text-sm font-semibold tabular-nums text-foreground"
          }
        >
          {totalHours.toFixed(2)}h
        </span>
      </div>
      <ol className="space-y-1 text-sm">
        {hops.map((hop, i) => (
          <li
            key={`${hop.port}-${i}`}
            className="flex items-center justify-between border-b py-1 last:border-0"
          >
            <span className="font-medium">
              <span className="mr-2 text-xs text-muted-foreground tabular-nums">
                {i + 1}.
              </span>
              {hop.port}
            </span>
            <span className="text-muted-foreground tabular-nums">
              {hop.leg_hours.toFixed(2)}h
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

// One reliability table row, read entirely from the route-level aggregate prop
// (never hardcoded). tabular-nums + .toFixed(2) match the PathColumn styling.
function ReliabilityRow({
  label,
  route,
  emphasis,
}: {
  label: string;
  route: Uc4RouteReliability;
  emphasis?: boolean;
}) {
  const numClass = emphasis
    ? "px-3 py-2 text-right tabular-nums font-semibold text-destructive"
    : "px-3 py-2 text-right tabular-nums text-foreground";
  return (
    <tr className="border-b last:border-0">
      <th scope="row" className="px-3 py-2 text-left font-medium">
        {label}
      </th>
      <td className={numClass}>{route.expected_delay_hours.toFixed(2)}</td>
      <td className={numClass}>{route.on_time_pct.toFixed(2)}</td>
      <td className={numClass}>{route.delay_risk_pct.toFixed(2)}</td>
      <td className={numClass}>{route.connectivity_score.toFixed(2)}</td>
    </tr>
  );
}

export function Uc4Summary({
  data,
  reliability,
}: {
  data: Uc4Envelope;
  reliability?: Uc4ReliabilitySidecar | null;
}) {
  const {
    baseline_path,
    reroute_path,
    baseline_hours,
    reroute_hours,
    delta,
    origin,
    dest,
  } = data;

  return (
    <section className="mt-8 space-y-6">
      {/* Prominent +76.22h delta callout. */}
      <Card>
        <CardHeader>
          <CardDescription>
            Added transit time when the chokepoint closes ({origin} → {dest})
          </CardDescription>
          <CardTitle className="flex flex-wrap items-baseline gap-3">
            <span className="text-3xl font-bold tracking-tight text-destructive">
              +{delta.toFixed(2)}h
            </span>
            <span className="text-sm font-normal text-muted-foreground">
              {baseline_hours.toFixed(2)}h baseline → {reroute_hours.toFixed(2)}h
              reroute
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm leading-relaxed text-muted-foreground">
          The shortest viable reroute adds <strong>+{delta.toFixed(2)}h</strong> of
          transit time, detouring through an extra port call versus the direct
          baseline lane.
        </CardContent>
      </Card>

      {/* Baseline vs reroute path hops, side by side. */}
      <Card>
        <CardHeader>
          <CardTitle>Baseline vs reroute path</CardTitle>
          <CardDescription>
            Per-leg hours for the direct baseline path and the shortest viable
            reroute.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-8 sm:flex-row">
          <PathColumn
            label="Baseline path"
            hops={baseline_path}
            totalHours={baseline_hours}
          />
          <PathColumn
            label="Reroute path"
            hops={reroute_path}
            totalHours={reroute_hours}
            emphasis
          />
        </CardContent>
      </Card>

      {/* Route-reliability aggregates derived from REAL World Bank LPI / UNCTAD LSCI
          priors. Rendered only when the sidecar is present (null-safe — a sidecar-less
          deploy leaves the rest of the page intact). All cells read from the prop. */}
      {reliability && (
        <Card>
          <CardHeader>
            <CardTitle>Route reliability: baseline vs reroute</CardTitle>
            <CardDescription>
              Derived from real World Bank LPI / UNCTAD LSCI reference-data priors
              (reference-data vintage, not real-time): expected delay, on-time and
              delay-risk probability, and weakest-link connectivity per route.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    Route
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Expected delay (h)
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    On-time %
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Delay-risk %
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Connectivity
                  </th>
                </tr>
              </thead>
              <tbody>
                <ReliabilityRow
                  label="Baseline"
                  route={reliability.baseline_reliability}
                />
                <ReliabilityRow
                  label="Reroute"
                  route={reliability.reroute_reliability}
                  emphasis
                />
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </section>
  );
}
