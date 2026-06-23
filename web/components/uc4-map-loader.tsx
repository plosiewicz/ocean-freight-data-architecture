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

import { useMemo } from "react";

import dynamic from "next/dynamic";

import { ArcLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { Layer, PickingInfo } from "@deck.gl/core";

import { resolveMapColors, type RGBA } from "@/lib/map-colors";
import type { Uc4Enriched, Uc4PathHopEnriched } from "@/lib/golden-types";

const UcMap = dynamic(() => import("./uc-map").then((m) => m.UcMap), {
  ssr: false,
  // Matches the shell's own fixed height so the layout doesn't jump while the WebGL
  // bundle loads (blank loading placeholder).
  loading: () => (
    <div className="h-[360px] rounded-lg border bg-muted/30 sm:h-[480px]" />
  ),
});

// A from→to arc segment between two consecutive hops (deck.gl is [lon, lat] order).
interface ArcSeg {
  from: [number, number];
  to: [number, number];
}

// A plotted hop marker + its UN/LOCODE label.
interface HopDatum {
  port: string;
  lon: number;
  lat: number;
}

// RESEARCH §Code Examples toSeg: turn an ordered hop list into consecutive from/to
// segment pairs. A 2-hop baseline yields 1 segment; the 3-hop reroute yields 2.
function toSegments(hops: Uc4PathHopEnriched[]): ArcSeg[] {
  return hops.slice(0, -1).map((h, i) => ({
    from: [h.lon, h.lat],
    to: [hops[i + 1].lon, hops[i + 1].lat],
  }));
}

export interface Uc4MapLoaderProps {
  envelope: Uc4Enriched;
}

export function Uc4MapLoader({ envelope }: Uc4MapLoaderProps) {
  // Resolve the theme colors ONCE on mount (RESEARCH Pitfall 5), not per-frame.
  const colors = useMemo(() => resolveMapColors(), []);

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
    // Baseline arc: muted hue, thin, flat (getHeight 0.3). USNYC → CNSHA direct.
    const baselineArc = new ArcLayer<ArcSeg>({
      id: "uc4-baseline-arc",
      data: toSegments(baseline_path),
      getSourcePosition: (d) => d.from,
      getTargetPosition: (d) => d.to,
      getSourceColor: colors.ARC_BASELINE as RGBA,
      getTargetColor: colors.ARC_BASELINE as RGBA,
      getWidth: 3,
      getHeight: 0.3,
      widthUnits: "pixels",
    });

    // Reroute arc: emerald hue, thicker, raised (getHeight 0.6). Multi-hop
    // USNYC → USLAX → CNSHA. The width + height difference is the color-blind-safe
    // second channel beyond hue (RESEARCH A4 lock).
    const rerouteArc = new ArcLayer<ArcSeg>({
      id: "uc4-reroute-arc",
      data: toSegments(reroute_path),
      getSourcePosition: (d) => d.from,
      getTargetPosition: (d) => d.to,
      getSourceColor: colors.ARC_REROUTE as RGBA,
      getTargetColor: colors.ARC_REROUTE as RGBA,
      getWidth: 4,
      getHeight: 0.6,
      widthUnits: "pixels",
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

    return [baselineArc, rerouteArc, hopMarkers, hopLabels];
  }, [baseline_path, reroute_path, hopData, colors]);

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
        {/* Arc legend — A4 locked corrected string (ArcLayer color/width/height only; the
            UI-SPEC stroke-pattern wording is superseded because ArcLayer cannot render that
            distinction). Each swatch uses the same --muted-foreground / --map-accent colors
            as its arc. */}
        <div className="mt-3 flex flex-col gap-1.5 text-xs">
          <span className="flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-6 rounded-full bg-muted-foreground"
              aria-hidden
            />
            <span className="text-muted-foreground">Baseline (muted, flat)</span>
          </span>
          <span className="flex items-center gap-2">
            <span
              className="inline-block h-1 w-6 rounded-full"
              style={{ backgroundColor: "var(--map-accent)" }}
              aria-hidden
            />
            <span className="text-muted-foreground">Reroute (emerald, raised)</span>
          </span>
        </div>
      </div>
      <p className="pointer-events-none text-xs text-muted-foreground">
        {hopData.length} of {intendedPortCount} points plotted
      </p>
    </div>
  );

  return <UcMap layers={layers} overlay={overlay} getTooltip={getTooltip} />;
}
