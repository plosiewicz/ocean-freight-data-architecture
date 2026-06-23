"use client";

// uc-dashboard — the rubric-centerpiece configurable OLAP dashboard for UC1/UC2.
// Owns the useState for breakdown / metric / view selections, defines the per-UC
// dimension + metric option maps, and renders <UcControlBar> (top, D-06) then either
// <UcChart> (bar for UC1 / line for UC2) or <UcDataTable>. EVERY reconfiguration is a
// pure client-side derivation over the already-fetched `rows` prop — no fetch, no
// serve(), no re-query (CHART-05). Behaves identically live or from golden because the
// page fetches once server-side and this component only re-derives display.

import { useMemo, useState } from "react";

import { UcChart } from "@/components/uc-chart";
import { UcControlBar, type SelectOption, type ViewMode } from "@/components/uc-control-bar";
import { UcColumn, UcDataTable } from "@/components/uc-data-table";
import type { Uc1Row, Uc2Row } from "@/lib/golden-types";

// ---- Per-UC option maps (CONTEXT D-04: dimensions + metrics) ----

interface UcConfig {
  chartKind: "bar" | "line";
  breakdownOptions: SelectOption[];
  metricOptions: SelectOption[];
  defaultBreakdown: string;
  defaultMetric: string;
  /** All displayable columns for the table view (id + label + numeric flag). */
  columns: UcColumn<Record<string, unknown>>[];
}

const UC1_CONFIG: UcConfig = {
  chartKind: "bar",
  breakdownOptions: [
    { value: "carrier_name", label: "Carrier" },
    { value: "lane_key", label: "Lane" },
    { value: "origin_unlocode", label: "Origin port" },
    { value: "dest_unlocode", label: "Destination port" },
  ],
  metricOptions: [
    { value: "on_time_pct", label: "On-time %" },
    { value: "avg_delay_hours", label: "Avg delay (hours)" },
    { value: "legs", label: "Leg count" },
  ],
  defaultBreakdown: "carrier_name",
  defaultMetric: "on_time_pct",
  columns: [
    { key: "carrier_name", label: "Carrier" },
    { key: "lane_key", label: "Lane" },
    { key: "origin_unlocode", label: "Origin" },
    { key: "dest_unlocode", label: "Dest" },
    { key: "legs", label: "Legs", numeric: true },
    { key: "on_time_pct", label: "On-time %", numeric: true },
    { key: "avg_delay_hours", label: "Avg delay (h)", numeric: true },
  ],
};

// Default UC2 port: a concrete real UN/LOCODE present in the golden set (not the field
// name "unlocode"). The breakdownOptions below are a placeholder — the dashboard derives
// the REAL port options at runtime from the distinct unlocode values in `rows`.
const UC2_DEFAULT_PORT = "USHOU";

const UC2_CONFIG: UcConfig = {
  chartKind: "line",
  // UC2 breaks down by port; the breakdown control is a real port selector whose options
  // are derived at runtime from the distinct unlocode values (see uc2PortOptions below).
  // This static entry is just a non-empty placeholder; the runtime options replace it.
  breakdownOptions: [{ value: UC2_DEFAULT_PORT, label: UC2_DEFAULT_PORT }],
  metricOptions: [
    { value: "avg_turnaround_hours", label: "Avg turnaround (hours)" },
    { value: "max_turnaround_hours", label: "Max turnaround (hours)" },
    { value: "calls", label: "Call count" },
  ],
  defaultBreakdown: UC2_DEFAULT_PORT,
  defaultMetric: "avg_turnaround_hours",
  columns: [
    { key: "unlocode", label: "Port" },
    { key: "call_date", label: "Call date" },
    { key: "calls", label: "Calls", numeric: true },
    { key: "avg_turnaround_hours", label: "Avg turnaround (h)", numeric: true },
    { key: "max_turnaround_hours", label: "Max turnaround (h)", numeric: true },
  ],
};

const CONFIG: Record<"uc1" | "uc2", UcConfig> = {
  uc1: UC1_CONFIG,
  uc2: UC2_CONFIG,
};

type DashboardRow = Uc1Row | Uc2Row;

export interface UcDashboardProps {
  ucId: "uc1" | "uc2";
  rows: DashboardRow[];
}

export function UcDashboard({ ucId, rows }: UcDashboardProps) {
  const config = CONFIG[ucId];

  const [breakdown, setBreakdown] = useState(config.defaultBreakdown);
  const [metric, setMetric] = useState(config.defaultMetric);
  const [view, setView] = useState<ViewMode>("chart");

  const metricLabel =
    config.metricOptions.find((o) => o.value === metric)?.label ?? metric;

  // UC2 breakdown options are the DISTINCT ports (UN/LOCODEs) present in the fetched rows
  // (USHOU/USLAX/USNYC/USSAV), derived at runtime so the selector stays correct if the
  // golden set changes. UC1 keeps its static dimension options. All client-side (CHART-05).
  const breakdownOptions = useMemo<SelectOption[]>(() => {
    if (ucId !== "uc2") return config.breakdownOptions;
    const ports = Array.from(
      new Set((rows as Uc2Row[]).map((r) => r.unlocode)),
    ).sort();
    return ports.length > 0
      ? ports.map((p) => ({ value: p, label: p }))
      : config.breakdownOptions;
  }, [ucId, rows, config.breakdownOptions]);

  // For UC1 the chart category IS the chosen breakdown dimension, so the raw golden rows
  // are GROUPED by that dimension and reduced to one record per distinct value (MEAN for
  // on_time_pct / avg_delay_hours, SUM for legs) — otherwise Recharts draws one bar per
  // raw row (up to 4 duplicate bars per carrier). For UC2 the chart is a per-port trend
  // line over call_date, narrowed to the selected port via the breakdown control. All
  // derived client-side over the already-fetched `rows` prop — no fetch/serve (CHART-05).
  const chartRows = useMemo<Record<string, unknown>[]>(() => {
    if (ucId === "uc2") {
      // Per-port trend: filter to the selected port (breakdown = a UN/LOCODE), then sort
      // ascending by call_date so the line is that port's 31-date trend, not all 124 rows.
      const filtered = (rows as Uc2Row[]).filter(
        (r) => r.unlocode === breakdown,
      );
      const sorted = [...filtered].sort((a, b) =>
        String(a.call_date).localeCompare(String(b.call_date)),
      );
      return sorted as unknown as Record<string, unknown>[];
    }

    // UC1: group by the chosen breakdown dimension and reduce each group to one record.
    const round2 = (n: number) => Math.round(n * 100) / 100;
    const groups = new Map<string, Uc1Row[]>();
    for (const row of rows as Uc1Row[]) {
      const key = String((row as unknown as Record<string, unknown>)[breakdown]);
      const bucket = groups.get(key);
      if (bucket) bucket.push(row);
      else groups.set(key, [row]);
    }

    const aggregated: Record<string, unknown>[] = [];
    for (const [key, group] of groups) {
      const n = group.length;
      const legs = group.reduce((sum, r) => sum + r.legs, 0);
      const onTimeMean =
        group.reduce((sum, r) => sum + r.on_time_pct, 0) / n;
      const delayMean =
        group.reduce((sum, r) => sum + r.avg_delay_hours, 0) / n;
      aggregated.push({
        // The category field IS the breakdown key, so categoryKey = breakdown still works.
        [breakdown]: key,
        legs,
        on_time_pct: round2(onTimeMean),
        avg_delay_hours: round2(delayMean),
      });
    }
    return aggregated;
  }, [ucId, rows, breakdown]);

  const categoryKey = ucId === "uc2" ? "call_date" : breakdown;

  const tableRows = rows as unknown as Record<string, unknown>[];

  return (
    <section className="mt-8 space-y-6">
      <UcControlBar
        breakdownOptions={breakdownOptions}
        breakdown={breakdown}
        onBreakdownChange={setBreakdown}
        metricOptions={config.metricOptions}
        metric={metric}
        onMetricChange={setMetric}
        view={view}
        onViewChange={setView}
        chartKind={config.chartKind}
      />

      {rows.length === 0 ? (
        <div className="flex h-64 items-center justify-center rounded-md border text-sm text-muted-foreground">
          No data available for this use case.
        </div>
      ) : view === "chart" ? (
        <UcChart
          rows={chartRows}
          categoryKey={categoryKey}
          metricKey={metric}
          metricLabel={metricLabel}
          chartType={config.chartKind}
        />
      ) : (
        <UcDataTable rows={tableRows} columns={config.columns} />
      )}
    </section>
  );
}
