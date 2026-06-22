"use client";

// uc-data-table — app-level wrapper over the shadcn table primitive (D-02).
// Sort/filter are lightweight client-side React state: plain array .sort()/.filter()
// over the already-fetched golden rows (UC1 22 rows, UC2 124 rows — NOT TanStack).
// Clicking a column header toggles its sort direction; an optional free-text filter
// narrows rows. Row highlight on hover (D-03). No fetching/re-query here (CHART-05).

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export interface UcColumn<TRow> {
  key: keyof TRow & string;
  label: string;
  /** Right-align + format numbers; left-align text. */
  numeric?: boolean;
}

export interface UcDataTableProps<TRow extends Record<string, unknown>> {
  rows: TRow[];
  columns: UcColumn<TRow>[];
}

type SortDir = "asc" | "desc";

function formatCell(value: unknown, numeric?: boolean): string {
  if (value == null) return "";
  if (numeric && typeof value === "number") {
    // Keep integers clean; show two decimals for fractional measures.
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

export function UcDataTable<TRow extends Record<string, unknown>>({
  rows,
  columns,
}: UcDataTableProps<TRow>) {
  const [sortKey, setSortKey] = useState<(keyof TRow & string) | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [filter, setFilter] = useState("");

  const view = useMemo(() => {
    const q = filter.trim().toLowerCase();
    let out = rows;
    if (q) {
      out = out.filter((row) =>
        columns.some((c) =>
          formatCell(row[c.key], c.numeric).toLowerCase().includes(q),
        ),
      );
    }
    if (sortKey) {
      // Copy before sorting so the source rows array is never mutated.
      out = [...out].sort((a, b) => {
        const av = a[sortKey];
        const bv = b[sortKey];
        let cmp: number;
        if (typeof av === "number" && typeof bv === "number") {
          cmp = av - bv;
        } else {
          cmp = String(av ?? "").localeCompare(String(bv ?? ""));
        }
        return sortDir === "asc" ? cmp : -cmp;
      });
    }
    return out;
  }, [rows, columns, filter, sortKey, sortDir]);

  function toggleSort(key: keyof TRow & string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  return (
    <div className="space-y-3">
      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter rows…"
        className={cn(
          "h-8 w-full max-w-xs rounded-md border bg-background px-3 text-sm shadow-xs outline-none",
          "focus-visible:ring-[3px] focus-visible:ring-ring/50",
        )}
      />
      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((col) => {
                const active = sortKey === col.key;
                return (
                  <TableHead
                    key={col.key}
                    className={cn(col.numeric && "text-right")}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(col.key)}
                      className={cn(
                        "inline-flex items-center gap-1 font-medium hover:text-foreground",
                        col.numeric ? "flex-row-reverse" : "",
                        active ? "text-foreground" : "text-muted-foreground",
                      )}
                    >
                      {col.label}
                      {active ? (
                        sortDir === "asc" ? (
                          <ArrowUp className="size-3.5" />
                        ) : (
                          <ArrowDown className="size-3.5" />
                        )
                      ) : (
                        <ArrowUpDown className="size-3.5 opacity-50" />
                      )}
                    </button>
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-24 text-center text-muted-foreground"
                >
                  No rows match the filter.
                </TableCell>
              </TableRow>
            ) : (
              view.map((row, i) => (
                <TableRow key={i} className="hover:bg-muted/50">
                  {columns.map((col) => (
                    <TableCell
                      key={col.key}
                      className={cn(col.numeric && "text-right tabular-nums")}
                    >
                      {formatCell(row[col.key], col.numeric)}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
