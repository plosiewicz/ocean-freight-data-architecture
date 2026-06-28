// uc4-map-loader.test.tsx — REQ-14-5 / REQ-14-6 string-testable coverage for the UC4
// scenario selector + closed-chokepoint label, without a WebGL canvas.
//
// The map itself is a deck.gl WebGL surface loaded via next/dynamic(ssr:false), so we
// render to STATIC HTML (react-dom/server, node env — no jsdom) and assert on the markup.
// Two stubs make that possible:
//   (1) the deck.gl layer classes are mocked to inert no-op constructors so the `layers`
//       useMemo can instantiate them without a GL context (we never inspect the layers
//       here — the contract under test is the OVERLAY markup), and
//   (2) `./uc-map` UcMap is mocked to render its `overlay` prop directly (the real one is
//       a dynamic ssr:false import that would render only its loading placeholder under
//       renderToStaticMarkup, hiding the overlay we need to assert on).
// resolveMapColors falls back to grey when `document` is undefined (node), so it is safe.

import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it, vi } from "vitest";

import type { Uc4Enriched } from "@/lib/golden-types";

// (1) Inert deck.gl layer stubs — constructing them must not touch a GL context.
vi.mock("@deck.gl/layers", () => ({
  PathLayer: class {},
  ScatterplotLayer: class {},
  TextLayer: class {},
}));
vi.mock("@deck.gl/geo-layers", () => ({
  TripsLayer: class {},
}));
vi.mock("@deck.gl/core", () => ({}));

// (2) The map mounts via `next/dynamic(() => import("./uc-map"))` with ssr:false. Under
// renderToStaticMarkup the real dynamic component renders only its loading placeholder
// (hiding the overlay). Mock next/dynamic so the returned component renders its `overlay`
// prop directly — that is where the testable selector + closed label live. We ignore the
// loader and return a passthrough; the deck.gl `layers` are never touched in markup.
vi.mock("next/dynamic", () => ({
  default: () => ({ overlay }: { overlay: React.ReactNode }) => (
    <div>{overlay}</div>
  ),
}));

import { Uc4MapLoader } from "@/components/uc4-map-loader";

// A minimal enriched envelope carrying three curated scenarios (Suez/Panama reroute +
// fragmentation-aware Gibraltar) — the golden SHAPE from 14-04.
const hop = (port: string, leg_hours: number, lon: number, lat: number) => ({
  port,
  leg_hours,
  lon,
  lat,
  waypoints: [[lon, lat]] as [number, number][],
});

const ENVELOPE: Uc4Enriched = {
  use_case: "UC4",
  origin: "ports/USNYC",
  dest: "ports/CNSHA",
  disabled_lanes: ["USNYC__CNSHA"],
  baseline_path: [hop("USNYC", 0, -74, 40.7), hop("CNSHA", 100, 121.8, 31.2)],
  reroute_path: [
    hop("USNYC", 0, -74, 40.7),
    hop("USLAX", 80, -118.2, 33.7),
    hop("CNSHA", 96, 121.8, 31.2),
  ],
  baseline_hours: 100,
  reroute_hours: 176,
  delta: 76,
  frozen_at_iso: "2026-06-28T00:00:00Z",
  scenarios: [
    {
      id: "suez",
      label: "Suez Canal closed (Asia ↔ US-East)",
      closed: "SUEZ",
      origin: "ports/USNYC",
      dest: "ports/CNSHA",
      fragmenting: false,
      reroute_available: true,
      disabled_lanes: ["USNYC__CNSHA"],
      baseline_path: [hop("USNYC", 0, -74, 40.7), hop("CNSHA", 100, 121.8, 31.2)],
      reroute_path: [
        hop("USNYC", 0, -74, 40.7),
        hop("USLAX", 80, -118.2, 33.7),
        hop("CNSHA", 96, 121.8, 31.2),
      ],
      baseline_hours: 100,
      reroute_hours: 176,
      delta: 76,
    },
    {
      id: "panama",
      label: "Panama Canal closed (Europe ↔ US-West)",
      closed: "PANAMA",
      origin: "ports/DEHAM",
      dest: "ports/USLAX",
      fragmenting: false,
      reroute_available: true,
      disabled_lanes: ["DEHAM__USLAX"],
      baseline_path: [hop("DEHAM", 0, 9.9, 53.5), hop("USLAX", 200, -118.2, 33.7)],
      reroute_path: [hop("DEHAM", 0, 9.9, 53.5), hop("USLAX", 260, -118.2, 33.7)],
      baseline_hours: 200,
      reroute_hours: 260,
      delta: 60,
    },
    {
      id: "gibraltar",
      label: "Strait of Gibraltar closed (Europe ↔ US-East)",
      closed: "GIBRALTAR",
      origin: "ports/DEHAM",
      dest: "ports/USNYC",
      fragmenting: true,
      reroute_available: false,
      disabled_lanes: ["DEHAM__USNYC"],
      baseline_path: [hop("DEHAM", 0, 9.9, 53.5), hop("USNYC", 150, -74, 40.7)],
      reroute_path: [],
      baseline_hours: 150,
      reroute_hours: 0,
      delta: 0,
    },
  ],
};

describe("Uc4MapLoader scenario selector + closed label (REQ-14-5/6)", () => {
  it("renders the first scenario's closed chokepoint value (REQ-14-5 — string-testable)", () => {
    const html = renderToStaticMarkup(<Uc4MapLoader envelope={ENVELOPE} />);
    // The default scenario is scenarios[0] = SUEZ; its `closed` value renders in the label
    // (the data-closed hook + the visible "Closed: SUEZ" copy), read from the golden.
    expect(html).toContain('data-closed="SUEZ"');
    expect(html).toContain("SUEZ");
  });

  it("renders exactly scenarios.length selector options (REQ-14-6)", () => {
    const html = renderToStaticMarkup(<Uc4MapLoader envelope={ENVELOPE} />);
    // Each curated scenario's label appears as a selectable option (the sr-only
    // enumeration — radix's portal-mounted SelectContent is absent from SSR markup).
    for (const s of ENVELOPE.scenarios!) {
      expect(html, `option ${s.id}`).toContain(s.label);
    }
    // And the option COUNT equals scenarios.length (no extra/missing options).
    const optionMatches = html.match(/data-scenario-option=/g) ?? [];
    expect(optionMatches.length).toBe(ENVELOPE.scenarios!.length);
  });
});
