// uc-header.test.tsx — APP-05 / D-02 coverage for the live/golden provenance pill.
//
// The pill is plain markup over a string prop (no browser-only API), so we render it
// to static HTML with react-dom/server and assert on the string — no jsdom, keeping
// this in the node environment alongside the lib/ tests (vitest.config include widened
// in Task 1). We assert the test-hook (data-served-by), the visible copy, the color
// triad class, and the copy rule (never the internal word "golden").

import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import { UcHeader } from "@/components/uc-header";

describe("UcHeader provenance pill (APP-05 / D-02)", () => {
  it("renders a green Live pill when servedBy='live'", () => {
    const html = renderToStaticMarkup(<UcHeader id="uc1" servedBy="live" />);
    expect(html).toContain('data-served-by="live"');
    expect(html).toContain("Live");
    expect(html).toContain("bg-emerald-100");
  });

  it("renders an amber Snapshot pill when servedBy='golden'", () => {
    const html = renderToStaticMarkup(<UcHeader id="uc1" servedBy="golden" />);
    expect(html).toContain('data-served-by="golden"');
    expect(html).toContain("Snapshot");
    expect(html).toContain("bg-amber-100");
  });

  it("renders no provenance pill when servedBy is undefined", () => {
    const html = renderToStaticMarkup(<UcHeader id="uc1" />);
    expect(html).not.toContain("data-served-by");
    expect(html).not.toContain("Snapshot");
  });

  it("never renders the internal word 'golden' as visible text (copy rule)", () => {
    const html = renderToStaticMarkup(<UcHeader id="uc1" servedBy="golden" />);
    // The data-served-by attribute legitimately carries "golden"; the VISIBLE copy
    // must not. Strip the attribute, then assert the word is absent from the rest.
    const withoutHook = html.replace(/data-served-by="golden"/g, "");
    expect(withoutHook).not.toContain("golden");
  });
});
