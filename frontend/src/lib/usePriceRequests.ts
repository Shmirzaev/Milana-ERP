import useSWRInfinite from "swr/infinite";
import { fetcher } from "@/lib/api";
import type { PriceCalculationRequest, PriceCalculationRequestPage } from "@/lib/priceCalculationRequests";

const PAGE_SIZE = 100;

export function usePriceRequests() {
  const swr = useSWRInfinite<PriceCalculationRequestPage>(
    (pageIndex, previousPageData) => {
      if (previousPageData && !previousPageData.has_more) return null;
      return `/api/price-calculation/requests?page=${pageIndex + 1}&page_size=${PAGE_SIZE}`;
    },
    fetcher,
    { refreshInterval: 15_000, refreshWhenHidden: false, refreshWhenOffline: false },
  );
  const pages = swr.data || [];
  const requests: PriceCalculationRequest[] = pages.flatMap((page) => page.items);
  const lastPage = pages[pages.length - 1];
  return {
    ...swr,
    requests,
    hasMore: Boolean(lastPage?.has_more),
    loadMore: () => swr.setSize((size) => size + 1),
    isLoadingMore: swr.isValidating && pages.length > 0,
  };
}
