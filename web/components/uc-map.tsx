"use client";

// uc-map — the shared reverse-controlled deck.gl + MapLibre map shell (Phase 10).
//
// Mirrors uc-chart.tsx's discipline: a "use client" viz that renders ALREADY-PREPARED
// inputs (here: a `layers` array + optional overlay/callout children) and NEVER fetches
// or re-queries. It is deliberately UC-agnostic — it knows nothing about UC3 ports vs UC4
// arcs; the per-UC loaders (uc3-map-loader.tsx, and 10-03's uc4 loader) build the layers
// + overlay and hand them in. That keeps this the single WebGL infrastructure both maps
// reuse (RESEARCH Pattern 1; PATTERNS shared-shell recommendation).
//
// Reverse-controlled pattern (RESEARCH Pattern 1, satisfies D-07): DeckGL is the root
// canvas/controller; <Map> from react-map-gl/maplibre is a CHILD backdrop. If the CARTO
// Positron CDN (D-06, tokenless) is unreachable the basemap fails silently while the
// deck.gl data layers keep rendering over a blank --background canvas — the map UC never
// hard-fails on a CDN outage. The mandatory maplibre CSS import (RESEARCH Pitfall 3) and
// an explicit pixel canvas height (RESEARCH Pitfall 6) are both required here.
//
// Colors are resolved from the oklch CSS-var tokens via map-colors.ts, never hex.

import { useState } from "react";

import { DeckGL } from "@deck.gl/react";
import type { Layer, PickingInfo } from "@deck.gl/core";
import { Map } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css"; // REQUIRED (Pitfall 3) — basemap renders unstyled without it

// CARTO Positron: maintained, tokenless, light cartography (D-06). A child of DeckGL so
// a CDN failure degrades to a blank canvas without killing the data layers (D-07).
const CARTO_POSITRON =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

// World view on load (D-01 / UI-SPEC §Shared map shell): all plotted ports + the 7
// chokepoints are visible without panning. Interactive pan/zoom stays enabled.
const INITIAL_VIEW_STATE = { longitude: 0, latitude: 20, zoom: 1.3 } as const;

export interface UcMapProps {
  /** Pre-built deck.gl layers (the loader owns color resolution + geometry). */
  layers: Layer[];
  /** Optional absolute-positioned overlay (callout card, footnote, toggle). */
  overlay?: React.ReactNode;
  /** deck.gl tooltip resolver — returns the hover text for a picked object. */
  getTooltip?: (info: PickingInfo) => { text: string } | null;
}

export function UcMap({ layers, overlay, getTooltip }: UcMapProps) {
  // D-07: track whether the CARTO basemap style failed to load so we can surface the
  // non-blocking "Basemap offline" chip. deck.gl layers render regardless.
  const [basemapFailed, setBasemapFailed] = useState(false);

  // Empty-state guard (mirrors uc-chart.tsx's rows.length === 0 path): if the null-island
  // join dropped every point so there are no layers, show the textual empty state instead
  // of a blank canvas (UI-SPEC Copywriting Contract). The persisting summary below still
  // carries the full result, so the UC never hard-fails.
  if (layers.length === 0) {
    return (
      <div className="flex h-[360px] flex-col items-center justify-center gap-1 rounded-lg border bg-muted/30 px-6 text-center sm:h-[480px]">
        <p className="text-lg font-semibold">Map data unavailable</p>
        <p className="text-sm text-muted-foreground">
          Coordinate lookup returned no plottable points. The text summary below
          shows the full result.
        </p>
      </div>
    );
  }

  return (
    <div className="relative h-[360px] overflow-hidden rounded-lg border bg-background sm:h-[480px]">
      <DeckGL
        initialViewState={INITIAL_VIEW_STATE}
        controller
        layers={layers}
        getTooltip={getTooltip}
      >
        {/* Basemap is a child backdrop (D-07). onError flips the offline chip but never
            blocks the data layers, which deck.gl draws over the --background canvas. */}
        <Map
          reuseMaps
          mapStyle={CARTO_POSITRON}
          onError={() => setBasemapFailed(true)}
        />
      </DeckGL>

      {overlay}

      {basemapFailed ? (
        <div className="pointer-events-none absolute bottom-2 right-2 rounded-md bg-card/90 px-2 py-1 text-xs text-muted-foreground shadow-sm">
          Basemap offline — showing data layers only
        </div>
      ) : null}
    </div>
  );
}
