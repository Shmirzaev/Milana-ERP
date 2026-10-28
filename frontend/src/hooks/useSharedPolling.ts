"use client";

import { useEffect, useMemo, useState } from "react";

/**
 * Shared polling configuration for SWR.
 *
 * Declared locally instead of importing SWR's `SWRConfiguration` so this module
 * stays a plain hook with no import of the data-fetching library.
 */
export type SharedPollingConfig = {
  /** Milliseconds between revalidations, or `0` to poll not at all. */
  refreshInterval: number;
  refreshWhenHidden: boolean;
  refreshWhenOffline: boolean;
  revalidateOnFocus: boolean;
  isOnline: () => boolean;
};

export const PRICE_REQUEST_POLL_INTERVAL_MS = 5_000;

function isBrowserOnline(): boolean {
  if (typeof navigator === "undefined") return true;
  return navigator.onLine !== false;
}

function isDocumentVisible(): boolean {
  if (typeof document === "undefined") return true;
  return document.visibilityState !== "hidden";
}

/**
 * One shared, visibility- and offline-aware polling hook.
 *
 * Every pricing surface used to declare its own `refreshInterval: 5_000`, so a
 * single browser tab left open on one of those pages kept a timer running
 * forever. This hook is the single definition of that behaviour:
 *
 * - the interval is `0` while the document is hidden, so SWR schedules no
 *   polling timer at all rather than merely skipping the fetch;
 * - the interval is `0` while the browser is offline;
 * - returning to the tab or regaining connectivity restores the interval and
 *   SWR revalidates immediately via `revalidateOnFocus`.
 *
 * Pass the result straight through as the `useSWR` options argument.
 */
export function useSharedPolling(intervalMs: number = PRICE_REQUEST_POLL_INTERVAL_MS): SharedPollingConfig {
  const [active, setActive] = useState<boolean>(() => isDocumentVisible() && isBrowserOnline());

  useEffect(() => {
    const sync = () => setActive(isDocumentVisible() && isBrowserOnline());
    // Re-check on mount: the document may have been hidden during SSR.
    sync();
    document.addEventListener("visibilitychange", sync);
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      document.removeEventListener("visibilitychange", sync);
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  return useMemo<SharedPollingConfig>(
    () => ({
      refreshInterval: active ? intervalMs : 0,
      refreshWhenHidden: false,
      refreshWhenOffline: false,
      revalidateOnFocus: true,
      isOnline: isBrowserOnline,
    }),
    [active, intervalMs],
  );
}
