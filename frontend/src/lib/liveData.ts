import type { SWRConfiguration } from "swr";

export const LIVE_DATA_VISIBLE_REFRESH_MS = 15_000;
export const FAST_LIVE_DATA_VISIBLE_REFRESH_MS = 10_000;
export const DASHBOARD_VISIBLE_REFRESH_MS = 30_000;

function liveOptions(refreshIntervalMs: number): SWRConfiguration {
  return {
    refreshInterval: refreshIntervalMs,
    refreshWhenHidden: true,
    refreshWhenOffline: false,
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    dedupingInterval: 2_000,
  };
}

/**
 * Use only for bounded live operational queues and stock/order lists.
 * Same-key SWR revalidation keeps the rendered data in place, so polling does
 * not replace the page with a loading state. Fixed intervals also resume
 * immediately after focus revalidation instead of inheriting a slower timer
 * that may have been scheduled while the tab was hidden.
 */
export const LIVE_DATA_SWR_OPTIONS = liveOptions(LIVE_DATA_VISIBLE_REFRESH_MS);

/** Faster polling for compact operational status boards. */
export const FAST_LIVE_DATA_SWR_OPTIONS = liveOptions(FAST_LIVE_DATA_VISIBLE_REFRESH_MS);

/** Slower polling for aggregate dashboards with heavier queries. */
export const DASHBOARD_SWR_OPTIONS = liveOptions(DASHBOARD_VISIBLE_REFRESH_MS);
