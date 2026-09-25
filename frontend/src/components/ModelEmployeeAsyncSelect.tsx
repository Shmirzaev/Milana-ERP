"use client";

import { useEffect, useMemo, useState } from "react";
import useSWRInfinite from "swr/infinite";
import SearchableSelect from "@/components/SearchableSelect";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

export type ModelEmployee = {
  id: number;
  full_name: string;
  department_id?: number | null;
  employee_no?: string | null;
  position?: string | null;
};
type EmployeePage = { rows: ModelEmployee[]; total: number };

export default function ModelEmployeeAsyncSelect({
  enabled, value, selectedEmployee, departmentIds, onChange, inputId, placeholder,
}: {
  enabled: boolean;
  value: number;
  selectedEmployee: ModelEmployee | null;
  departmentIds: Set<number>;
  onChange: (employee: ModelEmployee | null) => void;
  inputId: string;
  placeholder: string;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [search]);
  const { data: pages, size, setSize, isLoading, isValidating } = useSWRInfinite<EmployeePage>(
    (index, previous) => !enabled || !open || (previous && index * 50 >= previous.total) ? null
      : `/api/employees?page=${index + 1}&page_size=50&search=${encodeURIComponent(query)}`,
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const loaded = useMemo(() => pages?.flatMap((page) => page.rows) || [], [pages]);
  const employees = useMemo(() => {
    const byId = new Map<number, ModelEmployee>();
    if (value && selectedEmployee?.id === value) byId.set(value, selectedEmployee);
    for (const employee of loaded) {
      if (!departmentIds.size || departmentIds.has(Number(employee.department_id))) byId.set(employee.id, employee);
    }
    return byId;
  }, [departmentIds, loaded, selectedEmployee, value]);
  const total = pages?.[0]?.total ?? 0;

  return <SearchableSelect<number>
    inputId={inputId}
    value={value}
    options={[
      { value: 0, label: "-" },
      ...Array.from(employees.values()).map((employee) => ({
        value: employee.id,
        label: employee.full_name,
        searchText: [employee.employee_no, employee.position].filter(Boolean).join(" "),
      })),
    ]}
    onChange={(id, option) => onChange(Number(id) ? employees.get(Number(id)) || { id: Number(id), full_name: option.label } : null)}
    placeholder={placeholder}
    noResultsText={t("page.search.noMatches")}
    loadingText={t("common.loading")}
    loadMoreText={`${t("common.loadMore")} (${loaded.length} / ${total})`}
    loading={isLoading || isValidating}
    hasMore={Boolean(pages?.at(-1) && loaded.length < total)}
    onSearchChange={setSearch}
    onLoadMore={() => void setSize(size + 1)}
    onOpenChange={setOpen}
    serverFilter
  />;
}
