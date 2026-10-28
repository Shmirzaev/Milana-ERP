"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { api, fetcher } from "@/lib/api";

export type ModelOption = {
  id: number;
  code: string;
  name: string;
  thumbnail_url?: string | null;
};

export type ModelOptionPage = {
  items: ModelOption[];
  page: number;
  page_size: number;
  has_more: boolean;
};

export async function modelOptionItemsFetcher(url: string): Promise<ModelOption[]> {
  const page = await api.get<ModelOptionPage>(url);
  return page.items;
}

const IDS_KEY_PREFIX = "model-options-by-ids:";

export function modelOptionsByIdsKey(ids: Array<number | null | undefined>): string | null {
  const uniqueIds = Array.from(new Set(ids.map(Number).filter((id) => Number.isInteger(id) && id > 0))).sort((a, b) => a - b);
  return uniqueIds.length ? `${IDS_KEY_PREFIX}${uniqueIds.join(",")}` : null;
}

export async function modelOptionsByIdsFetcher(key: string): Promise<ModelOption[]> {
  const ids = key.slice(IDS_KEY_PREFIX.length).split(",").map(Number).filter((id) => id > 0);
  const byId = new Map<number, ModelOption>();
  for (let offset = 0; offset < ids.length; offset += 50) {
    const params = new URLSearchParams({ page: "1", page_size: "50" });
    for (const id of ids.slice(offset, offset + 50)) params.append("ids", String(id));
    const page = await api.get<ModelOptionPage>(`/api/model-options?${params.toString()}`);
    for (const option of page.items) byId.set(Number(option.id), option);
  }
  return Array.from(byId.values());
}

const PAGE_SIZE = 30;
const SEARCH_DEBOUNCE_MS = 180;

export function useModelOptions({
  selectedId,
  status,
  endpoint = "/api/model-options",
}: {
  selectedId?: number | null;
  status?: string;
  endpoint?: string;
} = {}) {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const controllers = useRef(new Set<AbortController>());

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  const requestKey = `${status || ""}\u0000${debouncedSearch}`;
  useEffect(() => {
    const activeControllers = controllers.current;
    return () => {
      activeControllers.forEach((controller) => controller.abort());
      activeControllers.clear();
    };
  }, [requestKey]);

  const pageFetcher = useCallback(async (url: string) => {
    const controller = new AbortController();
    controllers.current.add(controller);
    try {
      return await api.getWithSignal<ModelOptionPage>(url, controller.signal);
    } finally {
      controllers.current.delete(controller);
    }
  }, []);

  const getKey = useCallback((index: number, previous: ModelOptionPage | null) => {
    if (previous && !previous.has_more) return null;
    const params = new URLSearchParams({
      page: String(index + 1),
      page_size: String(PAGE_SIZE),
    });
    if (status) params.set("status", status);
    if (debouncedSearch) params.set("search", debouncedSearch);
    return `${endpoint}?${params.toString()}`;
  }, [debouncedSearch, endpoint, status]);

  const { data, error, isLoading, isValidating, size, setSize } = useSWRInfinite<ModelOptionPage>(
    getKey,
    pageFetcher,
    { revalidateFirstPage: false },
  );
  const previousRequestKey = useRef(requestKey);
  useEffect(() => {
    if (previousRequestKey.current === requestKey) return;
    previousRequestKey.current = requestKey;
    void setSize(1);
  }, [requestKey, setSize]);
  const selectedUrl = selectedId
    ? `${endpoint}?ids=${encodeURIComponent(String(selectedId))}&page_size=1`
    : null;
  const { data: selectedPage } = useSWR<ModelOptionPage>(selectedUrl, fetcher);

  const options = useMemo(() => {
    const byId = new Map<number, ModelOption>();
    for (const option of selectedPage?.items || []) byId.set(Number(option.id), option);
    for (const page of data || []) {
      for (const option of page.items || []) byId.set(Number(option.id), option);
    }
    return Array.from(byId.values());
  }, [data, selectedPage?.items]);

  const lastPage = data?.[data.length - 1];
  return {
    options,
    error,
    isLoading: isLoading || (isValidating && !data?.length),
    isLoadingMore: Boolean(isValidating && data?.length),
    hasMore: Boolean(lastPage?.has_more),
    setSearch,
    loadMore: () => setSize(size + 1),
  };
}
