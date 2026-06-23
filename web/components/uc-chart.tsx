"use client";

// uc-chart — app-level wrapper over the shadcn chart primitive (Recharts 3, D-01).
// Renders the active metric over the active breakdown/category, as either a bar or a
// line chart, with hover detail via ChartTooltip / ChartTooltipContent (D-03). All data
// is the already-fetched golden rows passed down by uc-dashboard — no fetching here
// (CHART-05). Series color is driven by the --chart-* CSS tokens in globals.css (D-04).

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

export type ChartType = "bar" | "line";

export interface UcChartProps {
  rows: ReadonlyArray<Record<string, unknown>>;
  /** Row field rendered along the category (X) axis, e.g. carrier_name or call_date. */
  categoryKey: string;
  /** Row field rendered as the measured value, e.g. on_time_pct or avg_turnaround_hours. */
  metricKey: string;
  /** Human label for the metric (legend + tooltip). */
  metricLabel: string;
  chartType: ChartType;
}

export function UcChart({
  rows,
  categoryKey,
  metricKey,
  metricLabel,
  chartType,
}: UcChartProps) {
  if (rows.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        No rows to chart.
      </div>
    );
  }

  // Recharts works off plain objects; the golden rows already are plain objects, so we
  // hand them straight through. The metric series is keyed by metricKey so the
  // --color-<metricKey> token (set by ChartContainer from the config below) applies.
  const config = {
    [metricKey]: {
      label: metricLabel,
      color: "var(--chart-1)",
    },
  } satisfies ChartConfig;

  const seriesColor = `var(--color-${metricKey})`;

  // Recharts 3 infers a strict TypedDataKey from the data prop's element type. The golden
  // rows are plain JSON records, so normalize to a loose record array — this lets the
  // string category/metric keys satisfy dataKey without per-UC chart type plumbing.
  const data = rows as Record<string, string | number>[];

  return (
    <ChartContainer config={config} className="min-h-64 w-full">
      {chartType === "bar" ? (
        <BarChart accessibilityLayer data={data} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey={categoryKey}
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            interval={0}
            minTickGap={8}
          />
          <YAxis tickLine={false} axisLine={false} tickMargin={8} width={48} />
          <ChartTooltip content={<ChartTooltipContent />} cursor={false} />
          <Bar dataKey={metricKey} fill={seriesColor} radius={4} />
        </BarChart>
      ) : (
        <LineChart accessibilityLayer data={data} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey={categoryKey}
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis tickLine={false} axisLine={false} tickMargin={8} width={48} />
          <ChartTooltip content={<ChartTooltipContent />} cursor={false} />
          <Line
            dataKey={metricKey}
            type="monotone"
            stroke={seriesColor}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      )}
    </ChartContainer>
  );
}
