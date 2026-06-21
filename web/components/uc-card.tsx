import Link from "next/link";

import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { UseCase } from "@/lib/use-cases";

// Store-tagged use-case card — the APP-01 hook. Each card carries a visible
// STORE TAG (BigQuery vs ArangoDB) so the right-store-per-workload split is
// legible at a glance, and wraps the whole card in a link to its /uc<n> stub.

const STORE_TAG_STYLE: Record<UseCase["store"], string> = {
  BigQuery: "bg-blue-100 text-blue-800 ring-blue-200",
  ArangoDB: "bg-emerald-100 text-emerald-800 ring-emerald-200",
};

export function UcCard({ uc }: { uc: UseCase }) {
  return (
    <Link
      href={uc.href}
      className="group block rounded-xl outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      aria-label={`${uc.title} — answered by ${uc.store}`}
    >
      <Card className="h-full gap-4 transition-shadow group-hover:shadow-md">
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {uc.id}
            </span>
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset",
                STORE_TAG_STYLE[uc.store]
              )}
              data-store-tag={uc.store}
            >
              {uc.store}
            </span>
          </div>
          <CardTitle className="text-lg">{uc.title}</CardTitle>
          <CardDescription>{uc.summary}</CardDescription>
        </CardHeader>
      </Card>
    </Link>
  );
}
