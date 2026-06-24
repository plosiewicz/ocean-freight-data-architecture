// page-fetcher.ts — the page-level creds-gated, data-layer-cached live-fetcher selector
// (APP-05 / DATA-06). SERVER-ONLY: it imports next/cache and is imported only by the RSC
// /ucN pages (never by a "use client" child), so no secret serializes into the client
// bundle (T-13-03). It reproduces the SAME creds gate the sibling /api/ucN route already
// uses — `serve("ucN", hasLiveCreds() ? ucNLiveFetcher : undefined)` — and adds ONE thing
// on top: it wraps the live fetcher in Next.js data caching so repeated dynamic page
// renders do NOT re-hit BigQuery/ArangoDB (DATA-06 stays satisfied off the prerender path).
//
// Why this exists (the Phase-13 gap fix): the live/golden provenance seam was wired onto
// the /api/ucN JSON routes but never onto the human-facing /ucN PAGES, so every page called
// serve("ucN") with NO live fetcher — making page-level served_by permanently "golden" and
// the UcHeader pill permanently "Snapshot". This selector is the second arg the pages now
// pass into serve(), making the pill truthful while keeping DATA-06 intact.
//
// Error discipline (D-09 / T-13-04): this helper adds NO catch that swallows a live-fetcher
// rejection. A thrown live fetcher rejects, serve()'s OWN catch performs the golden
// fall-back, and unstable_cache does NOT cache rejections — giving the honest
// "retry next request" behavior the dress rehearsal depends on. No error text reaches the
// rendered page (serve() discards it and returns golden with served_by="golden").

import { unstable_cache } from "next/cache";

import type { LiveFetcher } from "@/lib/serve";
import type { UcId } from "@/lib/golden-types";

/**
 * Default data-layer cache window in seconds. Matches DATA-06's route TTL (revalidate=300
 * on the /api/ucN routes) and stays comfortably under the ~1h Arango JWT window, so a cached
 * live envelope never outlives its credentials.
 */
export const LIVE_REVALIDATE_SECONDS = 300;

/**
 * The unstable_cache shape, kept structurally identical to next/cache's so the real
 * `unstable_cache` is assignable as the default arg. Its `Callback` constraint is
 * `(...args: any[]) => Promise<any>`; we mirror that exactly. Injected purely so the unit
 * test is hermetic (a counting/memoizing stub stands in for the real next/cache runtime);
 * production call sites use the real unstable_cache default below.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type CacheCallback = (...args: any[]) => Promise<any>;
export type CacheWrapper = <T extends CacheCallback>(
  cb: T,
  keyParts?: string[],
  options?: { revalidate?: number | false; tags?: string[] },
) => T;

/**
 * Build the second argument to serve() for a /ucN page.
 *
 * - If `hasCreds()` is false, return `undefined` — serve() then serves golden (honest
 *   Snapshot when creds are absent), exactly mirroring the route's
 *   `hasLiveCreds() ? ucNLiveFetcher : undefined` gate.
 * - Otherwise return a zero-arg async LiveFetcher that delegates to the cache-wrapper-wrapped
 *   underlying live fetcher, keyed stably per UC (["uc-live", uc]) with a ~300s revalidate so
 *   the live result is cached OFF the per-render path (repeated dynamic renders reuse it).
 *
 * The returned fetcher does NOT catch errors: a thrown underlying fetcher rejects so serve()
 * owns the golden fall-back (D-09), and the rejection is not cached.
 */
export function cachedLiveFetcher<U extends UcId>(
  uc: U,
  hasCreds: () => boolean,
  underlying: LiveFetcher<U>,
  cacheWrapper: CacheWrapper = unstable_cache,
): LiveFetcher<U> | undefined {
  if (!hasCreds()) return undefined;

  const wrapped = cacheWrapper(
    underlying as unknown as CacheCallback,
    ["uc-live", uc],
    { revalidate: LIVE_REVALIDATE_SECONDS },
  ) as unknown as LiveFetcher<U>;

  return () => wrapped();
}
