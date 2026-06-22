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

const UC2_CONFIG: UcConfig = {
  chartKind: "line",
  // UC2 breaks down by port; the time axis is call_date (used as the chart category).
  breakdownOptions: [{ value: "unlocode", label: "Port" }],
  metricOptions: [
    { value: "avg_turnaround_hours", label: "Avg turnaround (hours)" },
    { value: "max_turnaround_hours", label: "Max turnaround (hours)" },
    { value: "calls", label: "Call count" },
  ],
  defaultBreakdown: "unlocode",
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

  // For UC1 the chart category IS the chosen breakdown dimension. For UC2 the chart is a
  // trend line over call_date, optionally narrowed to one port via the breakdown control
  // (here the single port dimension just labels the series). All derived client-side.
  const chartRows = useMemo<Record<string, unknown>[]>(() => {
    if (ucId === "uc2") {
      // Time series: keep call_date as the category, sort ascending for a clean line.
      const sorted = [...rows].sort((a, b) =>
        String((a as Uc2Row).call_date).localeCompare(
          String((b as Uc2Row).call_date),
        ),
      );
      return sorted as unknown as Record<string, unknown>[];
    }
    return rows as unknown as Record<string, unknown>[];
  }, [ucId, rows]);

  const categoryKey = ucId === "uc2" ? "call_date" : breakdown;

  const tableRows = rows as unknown as Record<string, unknown>[];

  return (
    <section className="mt-8 space-y-6">
      <UcControlBar
        breakdownOptions={config.breakdownOptions}
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
