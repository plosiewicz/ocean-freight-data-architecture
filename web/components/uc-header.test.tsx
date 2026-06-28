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

// REQ-14-1 (review finding note 1): the "Why {store}: {workload}." rationale line was
// flagged as redundant on the UC headers. It is removed; the "Answered by: {store}"
// badge and the uc.summary text stay. These cases lock the removal in (regression
// guard) and assert the badge + summary survive so they can't be dropped by accident.
describe("UcHeader without the Why-store rationale line (REQ-14-1)", () => {
  it("does NOT render the 'Why {store}: {workload}.' rationale line for UC1", () => {
    const html = renderToStaticMarkup(<UcHeader id="uc1" servedBy="golden" />);
    // The removed line read e.g. "Why BigQuery: OLAP / dimensional." — assert the
    // "Why <store>:" fragment is gone (workload text overlaps nothing else here).
    expect(html).not.toContain("Why BigQuery");
    expect(html).not.toContain("OLAP / dimensional");
  });

  it("does NOT render the 'Why {store}: {workload}.' rationale line for UC2", () => {
    const html = renderToStaticMarkup(<UcHeader id="uc2" servedBy="golden" />);
    expect(html).not.toContain("Why BigQuery");
    expect(html).not.toContain("OLAP / dimensional");
  });

  it("still renders the 'Answered by' store badge and uc.summary for UC1", () => {
    const html = renderToStaticMarkup(<UcHeader id="uc1" servedBy="golden" />);
    expect(html).toContain("Answered by: BigQuery");
    expect(html).toContain(
      "Which routes, carriers, and ports have the worst schedule reliability",
    );
  });

  it("still renders the 'Answered by' store badge and uc.summary for UC2", () => {
    const html = renderToStaticMarkup(<UcHeader id="uc2" servedBy="golden" />);
    expect(html).toContain("Answered by: BigQuery");
    expect(html).toContain(
      "How congestion and dwell time at key ports trend over time",
    );
  });
});
