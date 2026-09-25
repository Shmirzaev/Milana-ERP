"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import SearchableSelect from "@/components/SearchableSelect";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Supplier = { id: number; name: string };
type SupplierPage = { rows: Supplier[]; total: number; has_more: boolean };

export default function SupplierAsyncSelect({
  value,
  onChange,
  inputId,
}: {
  value: number | null;
  onChange: (supplierId: number) => void;
  inputId: string;
}) {
  const { t } = useT();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data: pages, size, setSize, isLoading, isValidating } = useSWRInfinite<SupplierPage>(
    (index, previous) => {
      if (previous && !previous.has_more) return null;
      return `/api/suppliers?page=${index + 1}&page_size=50&q=${encodeURIComponent(query)}`;
    },
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const { data: selectedSupplier } = useSWR<Supplier>(value ? `/api/suppliers/${value}` : null, fetcher);
  const options = useMemo(() => {
    const byId = new Map<number, Supplier>();
    if (value) byId.set(value, selectedSupplier ?? { id: value, name: `#${value}` });
    for (const page of pages || []) {
      for (const supplier of page.rows) byId.set(supplier.id, supplier);
    }
    return [
      { value: 0, label: t("ph.supplier") },
      ...Array.from(byId.values()).map((supplier) => ({ value: supplier.id, label: supplier.name })),
    ];
  }, [pages, selectedSupplier, t, value]);

  return (
    <SearchableSelect
      inputId={inputId}
      value={value ?? 0}
      options={options}
      onChange={(supplierId) => onChange(Number(supplierId))}
      placeholder={t("ph.supplier")}
      noResultsText={t("page.search.noMatches")}
      loadingText={t("common.loading")}
      loadMoreText={t("common.loadMore")}
      loading={isLoading || isValidating}
      hasMore={Boolean(pages?.at(-1)?.has_more)}
      onSearchChange={setSearch}
      onLoadMore={() => void setSize(size + 1)}
      serverFilter
    />
  );
}
