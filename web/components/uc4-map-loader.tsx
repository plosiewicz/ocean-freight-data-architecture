"use client";

// uc4-map-loader — the "use client" wrapper that mounts the shared deck.gl shell for UC4
// and draws the baseline vs reroute paths as overlaid arcs (Phase 10, MAP-05 / D-05).
//
// Mirrors uc3-map-loader.tsx: a client wrapper that re-derives display over the
// ALREADY-FETCHED enriched envelope — no fetch, no serve(), no re-query (CHART-05 ethos /
// D-04). There is NO toggle here — both arcs are overlaid simultaneously; the contrast IS
// the story (D-05). The delta callout reads its values from the enriched envelope
// (delta / baseline_hours / reroute_hours), NEVER a hardcoded literal.
//
// deck.gl is ESM-only and touches window, so the actual map is loaded via next/dynamic
// with ssr:false — LEGAL here because this file is a Client Component (RESEARCH Pattern 2).
//
// RESEARCH A4 LOCKED: baseline and reroute are distinguished by COLOR + WIDTH + ARC HEIGHT,
// not stroke patterns. ArcLayer cannot render a solid-vs-broken stroke distinction
// (Pitfall 4), and the path-style extensions package is intentionally NOT a dependency. The
// color-blind second channel is the height/width difference, not hue alone (muted+flat
// baseline vs emerald+raised reroute).

import { useEffect, useMemo, useState } from "react";

import dynamic from "next/dynamic";

import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { TripsLayer } from "@deck.gl/geo-layers";
import type { Layer, PickingInfo } from "@deck.gl/core";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { resolveMapColors, type RGBA } from "@/lib/map-colors";
import { toTrip } from "@/lib/uc4-trip";
import type {
  Uc4Enriched,
  Uc4PathHopEnriched,
  Uc4ScenarioEnriched,
} from "@/lib/golden-types";

const UcMap = dynamic(() => import("./uc-map").then((m) => m.UcMap), {
  ssr: false,
  // Matches the shell's own fixed height so the layout doesn't jump while the WebGL
  // bundle loads (blank loading placeholder).
  loading: () => (
    <div className="h-[360px] rounded-lg border bg-muted/30 sm:h-[480px]" />
  ),
});

// The animation clock runs in the SAME hour-scale units as toTrip's cumulative-leg_hours
// timestamps (Pitfall 3 — NEVER epoch-ms). LOOP_LENGTH is ~the max cumulative hours across
// both trips plus a tail so the vessel fully arrives, fades, and the loop restarts cleanly;
// the +76.22h reroute delta is what the longer reroute trip makes self-evident on replay.
// Tuned for feel (D-04, Claude's discretion).
const LOOP_LENGTH = 520;
// Hours advanced per animation frame — small enough to read the traversal, large enough to
// complete the loop in a few seconds at ~60fps.
const TIME_STEP = 2;
// Trailing comet length behind the vessel, in the same hour units as currentTime.
const TRAIL_LENGTH = 60;

// A baked polyline datum for a PathLayer (deck.gl is [lon, lat] order).
interface PathDatum {
  path: [number, number][];
}

// A plotted hop marker + its UN/LOCODE label.
interface HopDatum {
  port: string;
  lon: number;
  lat: number;
}

// REQ-14-4: flatten an ordered hop list into ONE baked sea-route polyline by
// concatenating each hop's baked `waypoints` (already [lon,lat]). A hop with no
// waypoints contributes its own [lon,lat] endpoint so a legacy (pre-14-04) path still
// draws a straight polyline. Returns [] for an empty path (PathLayer draws nothing).
function toPolyline(hops: Uc4PathHopEnriched[]): [number, number][] {
  const pts: [number, number][] = [];
  for (const h of hops) {
    if (h.waypoints && h.waypoints.length > 0) {
      for (const w of h.waypoints) pts.push([w[0], w[1]]);
    } else {
      pts.push([h.lon, h.lat]);
    }
  }
  return pts;
}

export interface Uc4MapLoaderProps {
  envelope: Uc4Enriched;
}

export function Uc4MapLoader({ envelope }: Uc4MapLoaderProps) {
  // Resolve the theme colors ONCE on mount (RESEARCH Pitfall 5), not per-frame.
  const colors = useMemo(() => resolveMapColors(), []);

  // REQ-14-6: the curated scenarios behind the selector. A 14-04+ golden carries
  // `scenarios[]`; a legacy envelope (or a live ArangoDB fall-back without scenarios)
  // is folded into a SINGLE synthetic scenario from the legacy top-level fields so the
  // selector + label + map degrade gracefully (still one option, still a closed label
  // derived from disabled_lanes when present). Pure derivation over the fetched envelope.
  const scenarios: Uc4ScenarioEnriched[] = useMemo(() => {
    if (envelope.scenarios && envelope.scenarios.length > 0) {
      return envelope.scenarios;
    }
    return [
      {
        id: "default",
        label: "Disruption reroute",
        closed: envelope.disabled_lanes[0]?.split("__")[0] ?? "",
        origin: envelope.origin,
        dest: envelope.dest,
        fragmenting: false,
        reroute_available: envelope.reroute_path.length > 0,
        disabled_lanes: envelope.disabled_lanes,
        baseline_path: envelope.baseline_path,
        reroute_path: envelope.reroute_path,
        baseline_hours: envelope.baseline_hours,
        reroute_hours: envelope.reroute_hours,
        delta: envelope.delta,
      },
    ];
  }, [envelope]);

  // Selected scenario id (REQ-14-6). Defaults to the first scenario (planners front-load
  // the recommended scenario, mirroring scenarios[0] = the legacy top-level mirror).
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);

  // The selected scenario (fall back to scenarios[0] if the id ever goes stale).
  const scenario: Uc4ScenarioEnriched =
    scenarios.find((s) => s.id === scenarioId) ?? scenarios[0];

  // TripsLayer animation clock (MAP-06 / D-04). `playing` gates the rAF loop; `currentTime`
  // is the hour-scale clock fed to TripsLayer. Default playing=true so the loop runs hands-off
  // for the demo. This is pure presentation state over already-fetched coords — no re-query.
  const [playing, setPlaying] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);

  // rAF loop: while playing, advance the clock by TIME_STEP per frame modulo LOOP_LENGTH so
  // the baseline→reroute traversal continuously replays. Cancel the frame on pause/unmount so
  // we never leak a running loop. resolveMapColors stays OUT of this tick (Pitfall 5).
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      setCurrentTime((t) => (t + TIME_STEP) % LOOP_LENGTH);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  // All baseline/reroute geometry + headline numbers now come from the SELECTED scenario
  // (REQ-14-6), not the legacy top-level fields. `reroute_available`/`fragmenting` drive
  // the fragmentation-aware rendering (PROJECT D-12 / Option A): a fragmenting scenario
  // has an empty reroute_path + delta 0 — render its closed label + baseline + cosmetic
  // geometry, never assume a reroute exists.
  const {
    baseline_path,
    reroute_path,
    baseline_hours,
    reroute_hours,
    delta,
    reroute_available,
    closed,
  } = scenario;

  // The 10-01 join already dropped any null-coord hop, so the enriched paths are all
  // plottable. Still compute "N of M plotted": M = the intended hop count across both
  // paths (the union of distinct ports named in the scenario's baseline/reroute), N = the
  // hops that survived the coord join. We count distinct UN/LOCODEs so an intermediate
  // detour hop (present only in the reroute) is included exactly once.
  const intendedPortCount = useMemo(() => {
    const set = new Set<string>();
    for (const h of baseline_path) set.add(h.port);
    for (const h of reroute_path) set.add(h.port);
    return set.size;
  }, [baseline_path, reroute_path]);

  // Distinct plotted hop markers across both paths (USLAX appears once).
  const hopData: HopDatum[] = useMemo(() => {
    const byPort = new Map<string, HopDatum>();
    for (const h of [...baseline_path, ...reroute_path]) {
      if (!byPort.has(h.port)) {
        byPort.set(h.port, { port: h.port, lon: h.lon, lat: h.lat });
      }
    }
    return [...byPort.values()];
  }, [baseline_path, reroute_path]);

  const layers: Layer[] = useMemo(() => {
    // REQ-14-4: the BAKED sea-route polylines, drawn as PathLayers (getPath reads each
    // path's concatenated [lon,lat] waypoints verbatim — no runtime geometry, CSP-safe).
    // Baseline = muted + thin; reroute = emerald + thicker. The COLOR + WIDTH difference
    // is the color-blind-safe second channel (RESEARCH A4 lock — ArcLayer's height channel
    // doesn't apply to a flat PathLayer, so width carries the distinction).
    const baselinePath = new PathLayer<PathDatum>({
      id: "uc4-baseline-path",
      data: [{ path: toPolyline(baseline_path) }] as PathDatum[],
      getPath: (d) => d.path,
      getColor: colors.ARC_BASELINE as RGBA,
      getWidth: 3,
      widthUnits: "pixels",
      widthMinPixels: 2,
      capRounded: true,
      jointRounded: true,
    });

    // Reroute polyline: emerald, thicker. A FRAGMENTING scenario (Gibraltar, D-12 /
    // Option A) has an empty reroute_path → toPolyline returns [] → PathLayer draws
    // nothing. That is correct: the fragmentation story has no reroute to draw.
    const reroutePath = new PathLayer<PathDatum>({
      id: "uc4-reroute-path",
      data: reroute_available
        ? ([{ path: toPolyline(reroute_path) }] as PathDatum[])
        : [],
      getPath: (d) => d.path,
      getColor: colors.ARC_REROUTE as RGBA,
      getWidth: 4,
      widthUnits: "pixels",
      widthMinPixels: 3,
      capRounded: true,
      jointRounded: true,
      updateTriggers: { getPath: [scenarioId] },
    });

    // Hop markers so each endpoint (incl. the intermediate USLAX) is clearly placed.
    const hopMarkers = new ScatterplotLayer<HopDatum>({
      id: "uc4-hops",
      data: hopData,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: colors.PORT as RGBA,
      getRadius: 6,
      radiusUnits: "pixels",
      radiusMinPixels: 5,
      radiusMaxPixels: 9,
      stroked: false,
      pickable: true,
    });

    // UN/LOCODE label chips on each hop (UI-SPEC bg-background/90 chip): the intermediate
    // USLAX hop is therefore clearly marked. TextLayer with a background gives the chip.
    const hopLabels = new TextLayer<HopDatum>({
      id: "uc4-hop-labels",
      data: hopData,
      getPosition: (d) => [d.lon, d.lat],
      getText: (d) => d.port,
      getSize: 12,
      getColor: colors.PORT as RGBA,
      getPixelOffset: [0, -14],
      background: true,
      getBackgroundColor: [255, 255, 255, 230],
      backgroundPadding: [4, 2],
      fontFamily:
        "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
      fontWeight: 600,
    });

    // Animated vessel traversal (MAP-06 / D-04): a TripsLayer over the selected scenario's
    // BAKED multi-waypoint polylines so the vessel follows the real sea route. toTrip now
    // emits one timestamp PER POLYLINE POINT (interpolated per leg) so the traversal hugs
    // the curve. getTimestamps stay cumulative leg_hours — small hour-scale numbers in the
    // SAME units as currentTime/trailLength (Pitfall 3 — never epoch-ms). A fragmenting
    // scenario animates the baseline only (no reroute exists). Presentation-only, no re-query.
    const trips = [toTrip(baseline_path)];
    if (reroute_available) trips.push(toTrip(reroute_path));
    const tripsLayer = new TripsLayer<{
      path: [number, number][];
      timestamps: number[];
    }>({
      id: "uc4-trips",
      data: trips,
      getPath: (d) => d.path,
      getTimestamps: (d) => d.timestamps,
      getColor: colors.ARC_REROUTE as RGBA,
      currentTime,
      trailLength: TRAIL_LENGTH,
      fadeTrail: true,
      widthMinPixels: 4,
    });

    return [baselinePath, reroutePath, hopMarkers, hopLabels, tripsLayer];
  }, [
    baseline_path,
    reroute_path,
    reroute_available,
    scenarioId,
    hopData,
    colors,
    currentTime,
  ]);

  // Tooltip: hop marker = its UN/LOCODE.
  const getTooltip = (info: PickingInfo): { text: string } | null => {
    const obj = info.object as HopDatum | undefined;
    if (!obj || !("port" in obj)) return null;
    return { text: obj.port };
  };

  // Absolute overlay: the scenario selector (REQ-14-6), the closed-chokepoint label
  // (REQ-14-5), the delta callout, the legend, and the N-of-M footnote. ALL values are
  // read from the SELECTED scenario — NEVER hardcoded. The selector + label + callout are
  // fragmentation-aware: a scenario with no positive reroute (Gibraltar / Option A) renders
  // a fragmentation message instead of a reroute delta. Pure client state — no re-query.
  const overlay = (
    <div className="pointer-events-none absolute left-3 top-3 flex max-w-xs flex-col gap-2">
      <div className="pointer-events-auto rounded-lg border bg-card p-4 shadow-sm">
        {/* REQ-14-6: scenario selector — copied from uc3-map-loader's Select block. Each
            option is a curated disruption scenario; switching re-points every layer. */}
        <Select value={scenarioId} onValueChange={setScenarioId}>
          <SelectTrigger className="mb-3 w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {scenarios.map((s) => (
              <SelectItem key={s.id} value={s.id}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {/* REQ-14-6: a visually-hidden enumeration of the available scenarios. Radix's
            SelectContent options are portal-mounted only when the menu is open, so they are
            absent from static/SSR markup; this sr-only list keeps the full scenario set in
            the DOM for screen readers AND makes the option set string-testable (one
            data-scenario-option per curated scenario). */}
        <ul className="sr-only" aria-hidden>
          {scenarios.map((s) => (
            <li key={s.id} data-scenario-option={s.id}>
              {s.label}
            </li>
          ))}
        </ul>
        {/* REQ-14-5: the CLOSED chokepoint label — the scenario's `closed` value from the
            golden (never a literal). data-closed is the string-testable hook. */}
        <p
          data-closed={closed}
          className="mb-2 text-xs font-medium uppercase tracking-wide text-destructive"
        >
          Closed: {closed}
        </p>
        {reroute_available ? (
          <>
            <p className="text-3xl font-bold tracking-tight tabular-nums text-destructive">
              +{delta.toFixed(2)}h
            </p>
            <p className="mt-1 text-sm font-normal text-muted-foreground tabular-nums">
              {baseline_hours.toFixed(2)}h baseline → {reroute_hours.toFixed(2)}h
              reroute
            </p>
          </>
        ) : (
          // Fragmentation-aware (PROJECT D-12 / Option A): no reroute exists — closing this
          // chokepoint disconnects the route. Tell the fragmentation story, not a fake delta.
          <p className="text-sm leading-relaxed text-destructive">
            No reroute available — closing {closed} fragments the network on this
            corridor.
          </p>
        )}
        {/* Path legend — baseline vs reroute are baked sea-route POLYLINES now (PathLayer),
            distinguished by COLOR + WIDTH (the color-blind-safe second channel; a flat
            PathLayer has no arc-height channel). Each swatch uses the same
            --muted-foreground / --map-accent colors as its polyline. */}
        <div className="mt-3 flex flex-col gap-1.5 text-xs">
          <span className="flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-6 rounded-full bg-muted-foreground"
              aria-hidden
            />
            <span className="text-muted-foreground">Baseline (muted, thin)</span>
          </span>
          <span className="flex items-center gap-2">
            <span
              className="inline-block h-1 w-6 rounded-full"
              style={{ backgroundColor: "var(--map-accent)" }}
              aria-hidden
            />
            <span className="text-muted-foreground">Reroute (emerald, thick)</span>
          </span>
        </div>
        {/* Play/pause toggle (MAP-06 / D-04): gates the rAF loop that animates the vessel
            traversal. Default playing=true so the demo runs hands-off; pausing freezes the
            current frame. Pure client state — no re-query. */}
        <Button
          className="mt-3 w-full"
          variant={playing ? "outline" : "default"}
          onClick={() => setPlaying((p) => !p)}
        >
          {playing ? "Pause animation" : "Play animation"}
        </Button>
      </div>
      <p className="pointer-events-none text-xs text-muted-foreground">
        {hopData.length} of {intendedPortCount} points plotted
      </p>
    </div>
  );

  return <UcMap layers={layers} overlay={overlay} getTooltip={getTooltip} />;
}
