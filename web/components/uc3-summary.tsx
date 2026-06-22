import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Uc3Envelope } from "@/lib/golden-types";
import { cn } from "@/lib/utils";

// Render-only Server Component for /uc3 (Chokepoint risk exposure, ArangoDB / graph).
// Three sections over the frozen golden envelope (D-11): (1) the Gibraltar-closure
// reachability headline (29 open → 11 closed), (2) the Suez reroute-impact delta
// (+76.22h), and (3) the per-chokepoint transit-share table. Dependency-free —
// uses only the Card primitives + cn(), NO shadcn table (Plan 03 owns that install).
// This persists as the textual companion under the Phase-10 map (no rework thrown away).

export function Uc3Summary({ data }: { data: Uc3Envelope }) {
  const { closure_gibraltar, reroute_impact_suez, transit_share } = data;
  const reachabilityDrop =
    closure_gibraltar.open_reachable_total -
    closure_gibraltar.closed_reachable_total;

  return (
    <section className="mt-8 space-y-6">
      {/* (1) Closure reachability headline — the memorable 29 → 11 figure. */}
      <Card>
        <CardHeader>
          <CardDescription>
            Reachability when {closure_gibraltar.closed} closes
          </CardDescription>
          <CardTitle className="text-3xl font-bold tracking-tight">
            <span className="text-foreground">
              {closure_gibraltar.open_reachable_total}
            </span>{" "}
            <span className="text-muted-foreground">→</span>{" "}
            <span className="text-destructive">
              {closure_gibraltar.closed_reachable_total}
            </span>{" "}
            <span className="text-base font-medium text-muted-foreground">
              reachable origin→destination pairs
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm leading-relaxed text-muted-foreground">
          Closing the <strong>{closure_gibraltar.closed}</strong> chokepoint cuts
          network reachability from{" "}
          <strong>{closure_gibraltar.open_reachable_total}</strong> to{" "}
          <strong>{closure_gibraltar.closed_reachable_total}</strong> pairs — a loss
          of <strong>{reachabilityDrop}</strong> reachable pairs across{" "}
          {closure_gibraltar.open_origins} origins (open) /{" "}
          {closure_gibraltar.closed_origins} origins (closed).
        </CardContent>
      </Card>

      {/* (2) Reroute-impact callout — the +76.22h delta when SUEZ is disrupted. */}
      <Card>
        <CardHeader>
          <CardDescription>
            Reroute impact when {reroute_impact_suez.closed} closes (
            {reroute_impact_suez.origin} → {reroute_impact_suez.dest})
          </CardDescription>
          <CardTitle className="flex flex-wrap items-baseline gap-3">
            <span className="text-2xl font-semibold tracking-tight text-destructive">
              +{reroute_impact_suez.delta.toFixed(2)}h
            </span>
            <span className="text-sm font-normal text-muted-foreground">
              added transit time
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm leading-relaxed text-muted-foreground">
          Baseline transit{" "}
          <strong>{reroute_impact_suez.baseline_hours.toFixed(2)}h</strong> →
          reroute transit{" "}
          <strong>{reroute_impact_suez.reroute_hours.toFixed(2)}h</strong> when the
          shortest path must detour around {reroute_impact_suez.closed}.
        </CardContent>
      </Card>

      {/* (3) Per-chokepoint transit-share table — plain semantic HTML (no shadcn table). */}
      <Card>
        <CardHeader>
          <CardTitle>Transit share by chokepoint</CardTitle>
          <CardDescription>
            Share of network lanes transiting each maritime chokepoint.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-2 pr-4 font-medium">Chokepoint</th>
                <th className="py-2 pr-4 text-right font-medium">
                  Transiting / total lanes
                </th>
                <th className="py-2 text-right font-medium">Transit share</th>
              </tr>
            </thead>
            <tbody>
              {transit_share.map((row) => (
                <tr
                  key={row.chokepoint}
                  className={cn(
                    "border-b last:border-0",
                    row.transit_share_pct > 0
                      ? "text-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  <td className="py-2 pr-4 font-medium">{row.chokepoint}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {row.transiting_lanes} / {row.total_lanes}
                  </td>
                  <td className="py-2 text-right font-semibold tabular-nums">
                    {row.transit_share_pct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </section>
  );
}
