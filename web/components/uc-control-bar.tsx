"use client";

// uc-control-bar — controlled horizontal toolbar above the chart/table (D-06).
// Three controls: a breakdown-dimension dropdown, a metric dropdown, and a
// chart/table view toggle (the chart side is bar OR line per UC). It owns NO state —
// the dashboard passes current values + onChange callbacks (controlled component).
// Collapses to one column on mobile. Reconfiguration is instant because the dashboard
// re-derives display from the already-fetched rows (CHART-05) — nothing is fetched here.

import { BarChart3, LineChart as LineChartIcon, Table2 } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
}

/** "chart" renders the UC's native chart (bar for UC1, line for UC2); "table" the grid. */
export type ViewMode = "chart" | "table";

export interface UcControlBarProps {
  breakdownOptions: SelectOption[];
  breakdown: string;
  onBreakdownChange: (value: string) => void;

  metricOptions: SelectOption[];
  metric: string;
  onMetricChange: (value: string) => void;

  view: ViewMode;
  onViewChange: (view: ViewMode) => void;

  /** Icon for the chart-view button — BarChart3 (UC1) or LineChartIcon (UC2). */
  chartKind: "bar" | "line";

  breakdownLabel?: string;
  metricLabel?: string;
}

export function UcControlBar({
  breakdownOptions,
  breakdown,
  onBreakdownChange,
  metricOptions,
  metric,
  onMetricChange,
  view,
  onViewChange,
  chartKind,
  breakdownLabel = "Breakdown",
  metricLabel = "Metric",
}: UcControlBarProps) {
  const ChartIcon = chartKind === "bar" ? BarChart3 : LineChartIcon;

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
      <Field label={breakdownLabel}>
        <Select value={breakdown} onValueChange={onBreakdownChange}>
          <SelectTrigger size="sm" className="w-full sm:w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {breakdownOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label={metricLabel}>
        <Select value={metric} onValueChange={onMetricChange}>
          <SelectTrigger size="sm" className="w-full sm:w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {metricOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="View">
        {/* Segmented toggle built from buttonVariants (outline/secondary, size sm). */}
        <div className="inline-flex w-full overflow-hidden rounded-md border sm:w-auto">
          <ToggleButton
            active={view === "chart"}
            onClick={() => onViewChange("chart")}
          >
            <ChartIcon className="size-4" />
            {chartKind === "bar" ? "Bar" : "Line"}
          </ToggleButton>
          <ToggleButton
            active={view === "table"}
            onClick={() => onViewChange("table")}
          >
            <Table2 className="size-4" />
            Table
          </ToggleButton>
        </div>
      </Field>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-1 flex-col gap-1 sm:flex-none">
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  );
}

function ToggleButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        buttonVariants({
          variant: active ? "secondary" : "outline",
          size: "sm",
        }),
        // Flatten the segmented control: kill rounding + borders between segments.
        "flex-1 rounded-none border-0 shadow-none",
      )}
    >
      {children}
    </button>
  );
}
