// map-colors — client-only oklch CSS-var → deck.gl [r,g,b,a] bridge (Phase 10).
//
// recharts consumes CSS-var strings directly (see uc-chart.tsx), but deck.gl layer
// accessors (getFillColor / getLineColor) need a numeric [r,g,b,a] array. The browser
// is the only correct oklch→sRGB converter, so we let it do the conversion via the
// canonical 1×1 canvas parse (RESEARCH Pitfall 5): set fillStyle to the resolved CSS-var
// value, paint one pixel, read it back. NO hand-rolled oklch math, NO hardcoded hex —
// every map color derives from the existing globals.css oklch tokens so the map honors
// light/dark and stays consistent with the summaries below it (UI-SPEC §Color contract).
//
// Client-only: this touches `document` / `getComputedStyle`, so it must never be imported
// into a Server Component. It is consumed only by uc-map.tsx ("use client").

export type RGBA = [number, number, number, number];

/**
 * Resolve a CSS custom property (e.g. "--map-accent") to a deck.gl [r,g,b,a] array.
 * The browser parses the (possibly oklch) value into sRGB for us via a 1×1 canvas.
 * Falls back to opaque mid-grey if the canvas/2d context is unavailable (SSR-safety;
 * in practice this only runs client-side because the importing component is "use client").
 */
export function cssVarToRGBA(varName: string, alpha = 255): RGBA {
  if (typeof document === "undefined") return [128, 128, 128, alpha];
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim();
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext("2d");
  if (!ctx) return [128, 128, 128, alpha];
  ctx.fillStyle = value;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return [r, g, b, alpha];
}

/** The fixed token set every map layer color resolves from (UI-SPEC §Color contract). */
export interface MapColors {
  /** Port endpoint markers — neutral dark circle. */
  PORT: RGBA;
  /** Open / reachable chokepoint markers — emerald store color. */
  CHOKEPOINT_OPEN: RGBA;
  /** Closed chokepoint (after the closure toggle) — destructive red. */
  CHOKEPOINT_CLOSED: RGBA;
  /** UC4 baseline arc — muted/neutral solid (resolved here so 10-03 reuses it). */
  ARC_BASELINE: RGBA;
  /** UC4 reroute arc — emerald accent (resolved here so 10-03 reuses it). */
  ARC_REROUTE: RGBA;
}

/**
 * Read and return the fixed map color set ONCE (RESEARCH Pitfall 5: resolve on mount,
 * never per-feature-per-frame). Call from a useMemo/useState initializer in uc-map.tsx;
 * the returned object is then handed to every layer's color accessor.
 */
export function resolveMapColors(): MapColors {
  return {
    PORT: cssVarToRGBA("--foreground"),
    CHOKEPOINT_OPEN: cssVarToRGBA("--map-accent"),
    CHOKEPOINT_CLOSED: cssVarToRGBA("--destructive"),
    ARC_BASELINE: cssVarToRGBA("--muted-foreground"),
    ARC_REROUTE: cssVarToRGBA("--map-accent"),
  };
}
