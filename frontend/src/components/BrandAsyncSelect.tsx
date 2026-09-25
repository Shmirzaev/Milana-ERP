"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import SearchableSelect from "@/components/SearchableSelect";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Brand = { id: number; name: string };
type BrandPage = { rows: Brand[]; total: number; has_more: boolean };

export default function BrandAsyncSelect({
  value,
  onChange,
  inputId,
  required = false,
  activeOnly = false,
  selectedBrand,
}: {
  value: number | null;
  onChange: (brandId: number) => void;
  inputId: string;
  required?: boolean;
  activeOnly?: boolean;
  selectedBrand?: Brand | null;
}) {
  const { t } = useT();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data: pages, size, setSize, isLoading, isValidating } = useSWRInfinite<BrandPage>(
    (index, previous) => {
      if (previous && !previous.has_more) return null;
      return `/api/brands?page=${index + 1}&page_size=50&q=${encodeURIComponent(query)}${activeOnly ? "&active_only=true" : ""}`;
    },
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const knownSelection = selectedBrand?.id === value ? selectedBrand : null;
  const { data: selectedDetail } = useSWR<Brand>(value && !knownSelection ? `/api/brands/${value}` : null, fetcher);
  const options = useMemo(() => {
    const byId = new Map<number, Brand>();
    if (value) byId.set(value, knownSelection ?? selectedDetail ?? { id: value, name: `#${value}` });
    for (const page of pages || []) {
      for (const brand of page.rows) byId.set(brand.id, brand);
    }
    return Array.from(byId.values()).map((brand) => ({ value: brand.id, label: brand.name }));
  }, [knownSelection, pages, selectedDetail, value]);

  return (
    <SearchableSelect
      inputId={inputId}
      value={value}
      options={options}
      onChange={(brandId) => onChange(Number(brandId))}
      placeholder={t("ph.brand")}
      noResultsText={t("page.search.noMatches")}
      loadingText={t("common.loading")}
      loadMoreText={t("common.loadMore")}
      loading={isLoading || isValidating}
      hasMore={Boolean(pages?.at(-1)?.has_more)}
      onSearchChange={setSearch}
      onLoadMore={() => void setSize(size + 1)}
      serverFilter
      required={required}
    />
  );
}
