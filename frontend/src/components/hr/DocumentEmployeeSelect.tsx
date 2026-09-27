"use client";

import { useEffect, useMemo, useState } from "react";
import useSWRInfinite from "swr/infinite";
import SearchableSelect from "@/components/SearchableSelect";
import { fetcher } from "@/lib/api";

export type DocumentEmployee = { id: number; full_name: string };
type EmployeePage = { rows: DocumentEmployee[]; total: number };

export default function DocumentEmployeeSelect({
  enabled,
  value,
  selectedEmployee,
  onChange,
}: {
  enabled: boolean;
  value: number | null;
  selectedEmployee: DocumentEmployee | null;
  onChange: (employee: DocumentEmployee | null) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data: pages, size, setSize, isLoading, isValidating } = useSWRInfinite<EmployeePage>(
    (index, previous) => !enabled || !pickerOpen || (previous && index * 50 >= previous.total) ? null
      : `/api/employees?page=${index + 1}&page_size=50&search=${encodeURIComponent(query)}`,
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const loaded = useMemo(() => pages?.flatMap((page) => page.rows) || [], [pages]);
  const employees = useMemo(() => {
    const byId = new Map<number, DocumentEmployee>();
    if (value && selectedEmployee?.id === value) byId.set(value, selectedEmployee);
    for (const employee of loaded) byId.set(employee.id, employee);
    return byId;
  }, [loaded, selectedEmployee, value]);
  const total = pages?.[0]?.total ?? 0;

  return <SearchableSelect<number>
    value={value || 0}
    options={[
      { value: 0, label: "Select employee" },
      ...Array.from(employees.values()).map((employee) => ({ value: employee.id, label: employee.full_name })),
    ]}
    onChange={(id, option) => onChange(Number(id) ? employees.get(Number(id)) || { id: Number(id), full_name: option.label } : null)}
    placeholder="Select employee"
    noResultsText="No matching employees"
    loadingText="Loading…"
    loadMoreText={`Load more (${loaded.length} / ${total})`}
    loading={isLoading || isValidating}
    hasMore={Boolean(pages?.at(-1) && loaded.length < total)}
    onSearchChange={setSearch}
    onLoadMore={() => void setSize(size + 1)}
    onOpenChange={setPickerOpen}
    serverFilter
    required
  />;
}
