"use client";

import { useCallback, useMemo } from "react";
import useSWRInfinite from "swr/infinite";
import { fetcher } from "@/lib/api";
import type { PriceCalculationRequest } from "@/lib/priceCalculationRequests";
import { useSharedPolling } from "@/hooks/useSharedPolling";

export const PRICE_REQUEST_PAGE_SIZE = 50;

export function usePriceRequests() {
  const polling = useSharedPolling();
  const { data: pages, size, setSize, error, mutate, ...state } = useSWRInfinite<PriceCalculationRequest[]>(
    (index, previous: PriceCalculationRequest[] | null) => {
      if (previous && previous.length < PRICE_REQUEST_PAGE_SIZE) return null;
      const cursor = index > 0 && previous ? `&before_id=${previous[previous.length - 1].id}` : "";
      return `/api/price-calculation/requests?limit=${PRICE_REQUEST_PAGE_SIZE}${cursor}`;
    },
    fetcher,
    { ...polling, revalidateAll: true, persistSize: true },
  );
  const data = useMemo(() => {
    const seen = new Set<number>();
    return (pages || []).flat().filter((row) => {
      if (seen.has(row.id)) return false;
      seen.add(row.id);
      return true;
    });
  }, [pages]);
  const last = pages?.[pages.length - 1];
  const hasMore = !!last && last.length === PRICE_REQUEST_PAGE_SIZE;
  const missingPage = size > (pages?.length ?? 0);
  const isLoadingMore = missingPage && (!error || state.isValidating);
  const loadMore = useCallback(() => {
    if (missingPage) {
      if (error) void mutate().catch(() => undefined);
      return;
    }
    void setSize((count) => count + 1).catch(() => undefined);
  }, [missingPage, error, mutate, setSize]);
  return { ...state, error, mutate, data, hasMore, isLoadingMore, loadMore };
}
