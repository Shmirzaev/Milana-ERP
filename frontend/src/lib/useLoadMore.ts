"use client";

import { useEffect, useMemo } from "react";
import useSWRInfinite, { type SWRInfiniteConfiguration } from "swr/infinite";

type Key = string | readonly unknown[] | null;

// Adapt the existing page URLs to accumulated, fixed-size pages. The first key
// includes every filter and authorization scope, so changing either resets SWR.
export default function useLoadMore<T>(key: Key, fetchPage: (key: any) => Promise<T>, config?: SWRInfiniteConfiguration) {
  const url = typeof key === "string" ? key : key?.[0] as string | undefined;
  const parsed = url ? new URL(url, "http://erp.local") : null;
  const offsetMode = Boolean(parsed?.searchParams.has("offset"));
  const requestedPage = Math.max(1, Number(offsetMode
    ? Number(parsed?.searchParams.get("offset") || 0) / 50 + 1
    : parsed?.searchParams.get("page") || 1));
  if (parsed) {
    parsed.searchParams.delete("page");
    parsed.searchParams.delete("page_size");
    parsed.searchParams.delete("limit");
    parsed.searchParams.delete("offset");
  }
  const base = parsed ? `${parsed.pathname}?${parsed.searchParams}` : null;
  const scope = Array.isArray(key) ? key.slice(1) : null;
  const result = useSWRInfinite<T>((index, previous: any) => {
    if (!base || (previous && (previous.has_more === false || (index * 50 >= Number(previous.total))))) return null;
    const pageUrl = `${base}&${offsetMode ? `limit=50&offset=${index * 50}` : `page_size=50&page=${index + 1}`}`;
    return scope ? [pageUrl, ...scope] : pageUrl;
  }, fetchPage, { ...config, keepPreviousData: false, persistSize: false });
  const { setSize, size } = result;
  useEffect(() => { if (size !== requestedPage) void setSize(requestedPage); }, [base, requestedPage, setSize, size]);
  const data = useMemo(() => {
    if (!result.data?.length) return undefined;
    const pages = result.data as any[];
    const first = pages[0];
    const combined: any = { ...first, page: requestedPage, page_size: 50 };
    for (const field of ["rows", "items"]) {
      if (Array.isArray(first[field])) combined[field] = pages.flatMap((page) => page[field] || []);
    }
    return combined as T;
  }, [result.data, requestedPage]);
  return { ...result, data, isValidating: result.isValidating || (size !== requestedPage && !result.error) };
}
