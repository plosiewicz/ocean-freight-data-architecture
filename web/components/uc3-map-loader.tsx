"use client";

// uc3-map-loader — the "use client" wrapper that mounts the shared deck.gl shell for UC3
// and owns the closure-toggle state (Phase 10, MAP-01 / MAP-02).
//
// Mirrors uc-dashboard.tsx: a client wrapper that owns the interactive useState and
// re-derives display over the ALREADY-FETCHED enriched envelope — no fetch, no serve(),
// no re-query (CHART-05 ethos / D-04). The "Close Gibraltar" toggle is a pure client-state
// swap over the pre-frozen aggregate counts in envelope.closure_gibraltar; it issues no
// server round-trip and mutates no store (D-03/D-04).
//
// deck.gl is ESM-only and touches window, so the actual map is loaded via next/dynamic
// with ssr:false — which is LEGAL here because this file is a Client Component (RESEARCH
// Pattern 2). The page (a Server Component) cannot do that itself.

import { useMemo, useState } from "react";

import dynamic from "next/dynamic";

import { IconLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { Layer, PickingInfo } from "@deck.gl/core";

import { Button } from "@/components/ui/button";
import { resolveMapColors, type RGBA } from "@/lib/map-colors";
import type { Uc3Enriched } from "@/lib/golden-types";

const UcMap = dynamic(() => import("./uc-map").then((m) => m.UcMap), {
  ssr: false,
  // Matches the dashboard empty-state idiom + the shell's own fixed height.
  loading: () => (
    <div className="h-[360px] rounded-lg border bg-muted/30 sm:h-[480px]" />
  ),
});

// The chokepoint whose closure this map simulates. Read the display name from the matching
// transit_share entry (never the raw key) so the toggle/callout copy agrees with the data.
const GIBRALTAR_KEY = "GIBRALTAR";

// Inline white-fill SVG glyphs so deck.gl's getColor can tint them per-feature. The SHAPE
// changes between open (diamond) and closed (X), so open-vs-closed is distinguished by
// glyph shape in addition to hue (emerald vs red) — the mandatory color-blind rule.
const DIAMOND_SVG =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path d="M12 1 23 12 12 23 1 12Z" fill="white"/></svg>',
  );
const X_SVG =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path d="M4 4 20 20 M20 4 4 20" stroke="white" stroke-width="4" stroke-linecap="round"/></svg>',
  );

interface PortDatum {
  unlocode: string;
  lon: number;
  lat: number;
}

interface ChokepointDatum {
  key: string;
  name: string;
  lon: number;
  lat: number;
  pct: number;
  closed: boolean;
}

export interface Uc3MapLoaderProps {
  envelope: Uc3Enriched;
}

export function Uc3MapLoader({ envelope }: Uc3MapLoaderProps) {
  // Closure simulation is client-state only (D-03/D-04). Default = Gibraltar open.
  const [closed, setClosed] = useState(false);

  // Resolve the theme colors ONCE on mount (RESEARCH Pitfall 5), not per-frame.
  const colors = useMemo(() => resolveMapColors(), []);

  const { closure_gibraltar, transit_share, ports } = envelope;

  // The Gibraltar display name comes from the enriched transit_share entry (e.g. "Strait
  // of Gibraltar"), never the raw "GIBRALTAR" key (UI-SPEC copy rule).
  const gibraltarName =
    transit_share.find((c) => c.chokepoint === GIBRALTAR_KEY)?.name ??
    GIBRALTAR_KEY;

  // The 10-01 join already dropped null-coord ports, so envelope.ports are all plottable.
  // Still compute "N of M plotted": M = the intended explicit UC3 port set derived from the
  // envelope (origin + dest + the distinct ports named in the disabled lanes), N = those
  // that survived the coord join into envelope.ports.
  const intendedPortCount = useMemo(() => {
    const set = new Set<string>();
    const norm = (s: string) => s.replace(/^ports\//, "");
    set.add(norm(envelope.origin));
    set.add(norm(envelope.dest));
    for (const lane of envelope.reroute_impact_suez.disabled_lanes) {
      for (const p of lane.split("__")) set.add(p);
    }
    return set.size;
  }, [envelope.origin, envelope.dest, envelope.reroute_impact_suez.disabled_lanes]);

  const portData: PortDatum[] = useMemo(
    () => ports.map((p) => ({ unlocode: p.unlocode, lon: p.lon, lat: p.lat })),
    [ports],
  );

  const chokepointData: ChokepointDatum[] = useMemo(
    () =>
      transit_share.map((c) => ({
        key: c.chokepoint,
        name: c.name,
        lon: c.lon,
        lat: c.lat,
        pct: c.transit_share_pct,
        closed: closed && c.chokepoint === GIBRALTAR_KEY,
      })),
    [transit_share, closed],
  );

  const layers: Layer[] = useMemo(() => {
    const portLayer = new ScatterplotLayer<PortDatum>({
      id: "uc3-ports",
      data: portData,
      // deck.gl is [lon, lat] order (RESEARCH §Code Examples).
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: colors.PORT as RGBA,
      getRadius: 6,
      radiusUnits: "pixels",
      radiusMinPixels: 5,
      radiusMaxPixels: 9,
      stroked: false,
      pickable: true,
    });

    const chokepointLayer = new IconLayer<ChokepointDatum>({
      id: "uc3-chokepoints",
      data: chokepointData,
      getPosition: (d) => [d.lon, d.lat],
      // Shape encodes open/closed (diamond vs X) — hue + shape, not hue alone.
      getIcon: (d) => ({
        url: d.closed ? X_SVG : DIAMOND_SVG,
        width: 24,
        height: 24,
        mask: true, // mask:true lets getColor tint the white-fill glyph
      }),
      getColor: (d) =>
        d.closed ? colors.CHOKEPOINT_CLOSED : colors.CHOKEPOINT_OPEN,
      getSize: 22,
      sizeUnits: "pixels",
      pickable: true,
    });

    return [portLayer, chokepointLayer];
  }, [portData, chokepointData, colors]);

  // Tooltip: port = its UN/LOCODE (the enriched port set carries no name, only coords);
  // chokepoint = "{display name} — {pct}% of lanes transit" (UI-SPEC copy).
  const getTooltip = (info: PickingInfo): { text: string } | null => {
    const obj = info.object as PortDatum | ChokepointDatum | undefined;
    if (!obj) return null;
    if ("unlocode" in obj) return { text: obj.unlocode };
    return {
      text: `${obj.name} — ${obj.pct.toFixed(1)}% of lanes transit`,
    };
  };

  const { open_reachable_total, closed_reachable_total, open_origins } =
    closure_gibraltar;
  const reachabilityDrop = open_reachable_total - closed_reachable_total;

  // Absolute overlay: the closure toggle + reachability callout. All counts are read from
  // closure_gibraltar — NEVER hardcoded (UI-SPEC copy-consistency rule). The closed-state
  // sentence reuses the exact phrasing from uc3-summary.tsx so map + summary agree.
  const overlay = (
    <div className="pointer-events-none absolute left-3 top-3 flex max-w-xs flex-col gap-2">
      <div className="pointer-events-auto rounded-lg border bg-card p-4 shadow-sm">
        {closed ? (
          <>
            <p className="text-3xl font-semibold tracking-tight tabular-nums">
              <span className="text-foreground">{open_reachable_total}</span>{" "}
              <span className="text-muted-foreground">→</span>{" "}
              <span className="text-destructive">{closed_reachable_total}</span>{" "}
              <span className="text-sm font-normal text-muted-foreground">
                reachable pairs
              </span>
            </p>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              Closing {gibraltarName} cuts network reachability from{" "}
              {open_reachable_total} to {closed_reachable_total} reachable pairs —
              a loss of {reachabilityDrop} across {open_origins} origins.
            </p>
          </>
        ) : (
          <>
            <p className="text-3xl font-semibold tracking-tight tabular-nums">
              <span className="text-foreground">{open_reachable_total}</span>{" "}
              <span className="text-sm font-normal text-muted-foreground">
                reachable origin→destination pairs
              </span>
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              All 7 chokepoints open
            </p>
          </>
        )}
        <Button
          className="mt-3 w-full"
          variant={closed ? "outline" : "default"}
          onClick={() => setClosed((c) => !c)}
        >
          {closed ? `Reopen ${gibraltarName}` : "Close Gibraltar"}
        </Button>
      </div>
      <p className="pointer-events-none text-xs text-muted-foreground">
        {portData.length} of {intendedPortCount} ports plotted
      </p>
    </div>
  );

  return <UcMap layers={layers} overlay={overlay} getTooltip={getTooltip} />;
}
