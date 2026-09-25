"use client";

import { useMemo } from "react";
import useSWRInfinite from "swr/infinite";
import { fetcher } from "@/lib/api";

export type CuttingPassportPage<T> = {
  rows: T[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

export function useCuttingPassportPages<T>(cuttingDepartment: "CUT" | "ECT", search: string) {
  const query = search.trim();
  const { data, mutate, size, setSize, isLoading, isValidating } = useSWRInfinite<CuttingPassportPage<T>>(
    (index, previous) => previous && !previous.has_more ? null
      : `/api/cutting-passports?formula_version=20260706_ishlangan_kg&cutting_department_code=${cuttingDepartment}&page=${index + 1}&page_size=50${query ? `&q=${encodeURIComponent(query)}` : ""}`,
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const rows = useMemo(() => data?.flatMap((page) => page.rows) || [], [data]);
  return {
    rows,
    total: data?.at(-1)?.total || 0,
    hasMore: Boolean(data?.at(-1)?.has_more),
    loading: isLoading || isValidating,
    size,
    setSize,
    mutate,
  };
}
