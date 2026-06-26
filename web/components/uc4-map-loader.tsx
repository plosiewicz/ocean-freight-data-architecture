"use client";

// uc4-map-loader — the "use client" wrapper that mounts the shared deck.gl shell for UC4
// and draws the baseline vs reroute physical routes as overlaid path lines.
//
// Mirrors uc3-map-loader.tsx: a client wrapper that re-derives display over the
// ALREADY-FETCHED enriched envelope — no fetch, no serve(), no re-query (CHART-05 ethos /
// D-04). There is NO toggle here — both routes are overlaid simultaneously; the contrast IS
// the story (D-05). The delta callout reads its values from the enriched envelope
// (delta / baseline_hours / reroute_hours), NEVER a hardcoded literal.
//
// deck.gl is ESM-only and touches window, so the actual map is loaded via next/dynamic
// with ssr:false — LEGAL here because this file is a Client Component (RESEARCH Pattern 2).
//
// This map renders the actual port-to-port route geometry as continuous lines rather than
// abstract arc glyphs, making the physical route visible on the map.

import { useEffect, useMemo, useState } from "react";

import dynamic from "next/dynamic";

import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { TripsLayer } from "@deck.gl/geo-layers";
import type { Layer, PickingInfo } from "@deck.gl/core";

import { Button } from "@/components/ui/button";
import { resolveMapColors, type RGBA } from "@/lib/map-colors";
import { toTrip } from "@/lib/uc4-trip";
import type { Uc4Enriched, Uc4PathHopEnriched } from "@/lib/golden-types";

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

// A route line datum for deck.gl PathLayer (deck.gl is [lon, lat] order).
type Coords = [number, number];
interface RouteDatum {
  path: Coords[];
}

// A plotted hop marker + its UN/LOCODE label.
interface HopDatum {
  port: string;
  lon: number;
  lat: number;
}

// Interpolate a great-circle segment between two WGS84 points.
// This gives the UC4 route lines a more realistic oceanic curvature instead of a
// straight projected line between ports.
function interpolateGreatCircle(
  start: Coords,
  end: Coords,
  steps: number,
): Coords[] {
  const [lon0, lat0] = start;
  const [lon1, lat1] = end;
  const φ0 = (lat0 * Math.PI) / 180;
  const λ0 = (lon0 * Math.PI) / 180;
  const φ1 = (lat1 * Math.PI) / 180;
  const λ1 = (lon1 * Math.PI) / 180;
  const Δλ = λ1 - λ0;
  const sinφ0 = Math.sin(φ0);
  const cosφ0 = Math.cos(φ0);
  const sinφ1 = Math.sin(φ1);
  const cosφ1 = Math.cos(φ1);
  const cosΔλ = Math.cos(Δλ);
  const δ = Math.acos(Math.min(1, Math.max(-1, sinφ0 * sinφ1 + cosφ0 * cosφ1 * cosΔλ)));

  if (!Number.isFinite(δ) || δ === 0) {
    return [start, end];
  }

  const path: Coords[] = [];
  for (let i = 0; i <= steps; i += 1) {
    const f = i / steps;
    const sinδ = Math.sin(δ);
    const A = Math.sin((1 - f) * δ) / sinδ;
    const B = Math.sin(f * δ) / sinδ;
    const x = A * cosφ0 * Math.cos(λ0) + B * cosφ1 * Math.cos(λ1);
    const y = A * cosφ0 * Math.sin(λ0) + B * cosφ1 * Math.sin(λ1);
    const z = A * sinφ0 + B * sinφ1;
    const φ = Math.atan2(z, Math.sqrt(x * x + y * y));
    const λ = Math.atan2(y, x);
    path.push([(λ * 180) / Math.PI, (φ * 180) / Math.PI]);
  }
  return path;
}

// Turn an ordered hop list into a continuous route path, sampling each leg as a
// curved great-circle segment.
function toRoute(hops: Uc4PathHopEnriched[]): RouteDatum[] {
  if (hops.length === 0) return [{ path: [] }];

  const path: Coords[] = [];
  const segmentSteps = 64;
  for (let i = 0; i < hops.length - 1; i += 1) {
    const start: Coords = [hops[i].lon, hops[i].lat];
    const end: Coords = [hops[i + 1].lon, hops[i + 1].lat];
    const segment = interpolateGreatCircle(start, end, segmentSteps);
    if (i > 0) segment.shift();
    path.push(...segment);
  }

  if (hops.length === 1) {
    path.push([hops[0].lon, hops[0].lat]);
  }

  return [{ path }];
}

export interface Uc4MapLoaderProps {
  envelope: Uc4Enriched;
}

export function Uc4MapLoader({ envelope }: Uc4MapLoaderProps) {
  // Resolve the theme colors ONCE on mount (RESEARCH Pitfall 5), not per-frame.
  const colors = useMemo(() => resolveMapColors(), []);

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

  const { baseline_path, reroute_path, baseline_hours, reroute_hours, delta } =
    envelope;

  // The 10-01 join already dropped any null-coord hop, so the enriched paths are all
  // plottable. Still compute "N of M plotted": M = the intended hop count across both
  // paths (the union of distinct ports named in the original baseline/reroute), N = the
  // hops that survived the coord join. We count distinct UN/LOCODEs so the intermediate
  // USLAX (present only in the reroute) is included exactly once.
  const intendedPortCount = useMemo(() => {
    const set = new Set<string>();
    for (const h of envelope.baseline_path) set.add(h.port);
    for (const h of envelope.reroute_path) set.add(h.port);
    return set.size;
  }, [envelope.baseline_path, envelope.reroute_path]);

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
    // Baseline route: muted hue, thin line. USNYC → CNSHA direct.
    const baselineRoute = new PathLayer<RouteDatum>({
      id: "uc4-baseline-route",
      data: toRoute(baseline_path),
      getPath: (d) => d.path,
      getColor: colors.ARC_BASELINE as RGBA,
      getWidth: 3,
      widthUnits: "pixels",
      rounded: true,
      capRounded: true,
      jointRounded: true,
    });

    // Reroute route: emerald hue, thicker. Draws the physical reroute path through
    // USLAX and across the Pacific as a continuous route line.
    const rerouteRoute = new PathLayer<RouteDatum>({
      id: "uc4-reroute-route",
      data: toRoute(reroute_path),
      getPath: (d) => d.path,
      getColor: colors.ARC_REROUTE as RGBA,
      getWidth: 4,
      widthUnits: "pixels",
      rounded: true,
      capRounded: true,
      jointRounded: true,
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

    // Animated vessel traversal (MAP-06 / D-04): one TripsLayer carrying BOTH trips so the
    // vessel runs the baseline then the (longer) reroute on a continuous loop, making the
    // +76.22h delta self-evident. getTimestamps come from toTrip's cumulative leg_hours —
    // small hour-scale numbers in the SAME units as currentTime/trailLength (Pitfall 3 — never
    // epoch-ms). Presentation-only over the already-fetched enriched paths; no re-query.
    const tripsLayer = new TripsLayer<{
      path: [number, number][];
      timestamps: number[];
    }>({
      id: "uc4-trips",
      data: [toTrip(baseline_path), toTrip(reroute_path)],
      getPath: (d) => d.path,
      getTimestamps: (d) => d.timestamps,
      getColor: colors.ARC_REROUTE as RGBA,
      currentTime,
      trailLength: TRAIL_LENGTH,
      fadeTrail: true,
      widthMinPixels: 4,
    });

    return [baselineRoute, rerouteRoute, hopMarkers, hopLabels, tripsLayer];
  }, [baseline_path, reroute_path, hopData, colors, currentTime]);

  // Tooltip: hop marker = its UN/LOCODE.
  const getTooltip = (info: PickingInfo): { text: string } | null => {
    const obj = info.object as HopDatum | undefined;
    if (!obj || !("port" in obj)) return null;
    return { text: obj.port };
  };

  // Absolute overlay: the delta callout, arc legend, and N-of-M footnote. The Display
  // "+{delta}h" value and the "baseline → reroute" body are read from the envelope — NEVER
  // hardcoded — and reuse the exact phrasing from uc4-summary.tsx so map + summary agree.
  const overlay = (
    <div className="pointer-events-none absolute left-3 top-3 flex max-w-xs flex-col gap-2">
      <div className="pointer-events-auto rounded-lg border bg-card p-4 shadow-sm">
        <p className="text-3xl font-bold tracking-tight tabular-nums text-destructive">
          +{delta.toFixed(2)}h
        </p>
        <p className="mt-1 text-sm font-normal text-muted-foreground tabular-nums">
          {baseline_hours.toFixed(2)}h baseline → {reroute_hours.toFixed(2)}h
          reroute
        </p>
        {/* Route legend — show the actual route lines instead of abstract arcs. */}
        <div className="mt-3 flex flex-col gap-1.5 text-xs">
          <span className="flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-6 rounded-full bg-muted-foreground"
              aria-hidden
            />
            <span className="text-muted-foreground">Baseline route (muted)</span>
          </span>
          <span className="flex items-center gap-2">
            <span
              className="inline-block h-1 w-6 rounded-full"
              style={{ backgroundColor: "var(--map-accent)" }}
              aria-hidden
            />
            <span className="text-muted-foreground">Reroute route (emerald)</span>
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
