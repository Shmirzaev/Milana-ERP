"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import SearchableSelect from "@/components/SearchableSelect";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Customer = { id: number; name: string };
type CustomerPage = { rows: Customer[]; total: number; page: number; page_size: number };

export default function CustomerAsyncSelect({
  value,
  onChange,
  selectedCustomer,
}: {
  value: number | null;
  onChange: (customerId: number | null, customer?: Customer) => void;
  selectedCustomer?: Customer | null;
}) {
  const { t } = useT();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data: pages, size, setSize, isLoading, isValidating } = useSWRInfinite<CustomerPage>(
    (index, previous) => {
      if (previous && previous.page * previous.page_size >= previous.total) return null;
      return `/api/customers?page=${index + 1}&page_size=50&q=${encodeURIComponent(query)}`;
    },
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const knownSelection = selectedCustomer?.id === value ? selectedCustomer : null;
  const { data: selectedDetail } = useSWR<Customer>(
    value && !knownSelection ? `/api/customers/${value}` : null,
    fetcher,
  );
  const options = useMemo(() => {
    const byId = new Map<number, Customer>();
    if (value) byId.set(value, knownSelection ?? selectedDetail ?? { id: value, name: `#${value}` });
    for (const page of pages || []) {
      for (const customer of page.rows) byId.set(customer.id, customer);
    }
    return [
      { value: 0, label: t("newso.customerSelect") },
      ...Array.from(byId.values()).map((customer) => ({ value: customer.id, label: customer.name })),
    ];
  }, [knownSelection, pages, selectedDetail, t, value]);
  const lastPage = pages?.at(-1);

  return (
    <SearchableSelect
      value={value ?? 0}
      options={options}
      onChange={(customerId, option) => onChange(Number(customerId) || null, Number(customerId) ? { id: Number(customerId), name: option.label } : undefined)}
      placeholder={t("newso.customerSelect")}
      noResultsText={t("page.search.noMatches")}
      loadingText={t("common.loading")}
      loadMoreText={t("common.loadMore")}
      loading={isLoading || isValidating}
      hasMore={Boolean(lastPage && lastPage.page * lastPage.page_size < lastPage.total)}
      onSearchChange={setSearch}
      onLoadMore={() => void setSize(size + 1)}
      serverFilter
    />
  );
}
