// page-fetcher.test.ts — Wave-7 hermetic contract for the page-level creds-gated,
// data-layer-cached live-fetcher selector (APP-05 / DATA-06). This is the unit the four
// /ucN PAGES call to feed serve()'s second argument. It mirrors arango.test.ts's
// dependency-injection style: a stub creds-predicate, a counting/throwing underlying
// fetcher, and an INJECTED counting cache-wrapper stand in for the real next/cache
// unstable_cache — so every assertion runs with NO Next runtime and NO live store.
//
// The four behaviors (matching the plan's <behavior> block):
//   1. creds true + supplied fetcher -> cachedLiveFetcher returns a callable; awaiting it
//      yields the underlying live fetcher's envelope.
//   2. creds false -> cachedLiveFetcher returns undefined (serve() then serves golden —
//      honest Snapshot when creds are absent).
//   3. (DATA-06 no-regression) creds present, the returned fetcher invoked TWICE within
//      the cache window calls the UNDERLYING fetcher only ONCE — the cache wrapper owns the
//      second call. Proven with a counting cache-wrapper + a call-counting fetcher.
//   4. a thrown underlying fetcher PROPAGATES (not swallowed here, so serve()'s catch does
//      the golden fall-back) AND the error is NOT cached (a later success still reaches the
//      underlying fetcher).

import { describe, expect, it } from "vitest";

import { cachedLiveFetcher } from "@/lib/page-fetcher";
import type { EnvelopeByUc, UcId } from "@/lib/golden-types";

// A minimal uc1 envelope fixture — only the shape serve()/the test cares about.
function uc1Env(): EnvelopeByUc["uc1"] {
  return {
    frozen_at_iso: "2026-01-01T00:00:00.000Z",
    query: "sql/uc1_eta_reliability.sql",
    row_count: 0,
    rows: [],
    store: "bigquery",
    use_case: "UC1",
  };
}

// A counting cache-wrapper with the unstable_cache shape: (cb, keyParts?, options?) -> cb-like.
// It records how many times it WRAPPED a fn and how many times the WRAPPED fn was invoked,
// and crucially MEMOIZES the underlying result by keyParts (only caching resolved values, so
// a rejection is NOT cached) — the hermetic stand-in for next/cache's revalidate window.
function makeCountingCache() {
  const calls = { wraps: 0, invocations: 0 };
  const store = new Map<string, unknown>();
  // Match next/cache's Callback constraint exactly: (...args: any[]) => Promise<any>.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const wrap = <T extends (...a: any[]) => Promise<any>>(
    cb: T,
    keyParts?: string[],
    options?: { revalidate?: number | false; tags?: string[] },
  ): T => {
    calls.wraps += 1;
    void options;
    const key = (keyParts ?? []).join("|");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const wrapped = (async (...args: any[]) => {
      calls.invocations += 1;
      if (store.has(key)) return store.get(key);
      const result = await cb(...args); // a rejection here propagates and is NOT stored
      store.set(key, result);
      return result;
    }) as unknown as T;
    return wrapped;
  };
  return { wrap, calls };
}

const credsTrue = () => true;
const credsFalse = () => false;

describe("cachedLiveFetcher — creds gate", () => {
  it("creds true: returns a callable that resolves the underlying live fetcher's envelope", async () => {
    const env = uc1Env();
    const underlying = async () => env;
    const cache = makeCountingCache();
    const fetcher = cachedLiveFetcher(
      "uc1" as UcId,
      credsTrue,
      underlying,
      cache.wrap,
    );
    expect(typeof fetcher).toBe("function");
    const out = await fetcher!();
    expect(out).toEqual(env);
  });

  it("creds false: returns undefined (so serve() serves golden — honest Snapshot)", () => {
    const underlying = async () => uc1Env();
    const cache = makeCountingCache();
    const fetcher = cachedLiveFetcher(
      "uc1" as UcId,
      credsFalse,
      underlying,
      cache.wrap,
    );
    expect(fetcher).toBeUndefined();
  });
});

describe("cachedLiveFetcher — DATA-06 no-regression (cache wrap)", () => {
  it("two invocations within the window hit the UNDERLYING fetcher only once", async () => {
    let underlyingCalls = 0;
    const underlying = async () => {
      underlyingCalls += 1;
      return uc1Env();
    };
    const cache = makeCountingCache();
    const fetcher = cachedLiveFetcher(
      "uc1" as UcId,
      credsTrue,
      underlying,
      cache.wrap,
    )!;
    await fetcher();
    await fetcher();
    // The cache wrapper was invoked twice (per render) but the underlying live fetcher only once.
    expect(cache.calls.invocations).toBe(2);
    expect(underlyingCalls).toBe(1);
  });
});

describe("cachedLiveFetcher — error propagation (serve() owns the golden fall-back)", () => {
  it("a thrown underlying fetcher REJECTS (not swallowed) and is NOT cached", async () => {
    let underlyingCalls = 0;
    let shouldThrow = true;
    const env = uc1Env();
    const underlying = async () => {
      underlyingCalls += 1;
      if (shouldThrow) throw new Error("simulated live failure");
      return env;
    };
    const cache = makeCountingCache();
    const fetcher = cachedLiveFetcher(
      "uc1" as UcId,
      credsTrue,
      underlying,
      cache.wrap,
    )!;
    // First call throws -> the helper does NOT swallow it; serve()'s catch would fall back.
    await expect(fetcher()).rejects.toThrow("simulated live failure");
    // The error was NOT cached: a later success still reaches the underlying fetcher.
    shouldThrow = false;
    const out = await fetcher();
    expect(out).toEqual(env);
    expect(underlyingCalls).toBe(2); // both calls reached the underlying fetcher
  });
});
