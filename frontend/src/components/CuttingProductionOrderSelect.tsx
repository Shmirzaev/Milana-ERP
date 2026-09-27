"use client";

import { useEffect, useMemo, useState } from "react";
import useSWRInfinite from "swr/infinite";
import SearchableSelect from "@/components/SearchableSelect";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";

export type CuttingProductionOrder = {
  id: number;
  production_no: string;
  order_no?: string | null;
  model_code?: string | null;
  model_id?: number | null;
  source_type?: string | null;
  planned_quantity?: number | null;
  estimated_material_amount?: number | null;
};

type OrderPage = { rows: CuttingProductionOrder[]; total: number; has_more: boolean };

export default function CuttingProductionOrderSelect({
  value,
  selectedOrder,
  cuttingDepartment,
  onChange,
  inputId,
}: {
  value: number | string | null;
  selectedOrder: CuttingProductionOrder | null;
  cuttingDepartment: "CUT" | "ECT";
  onChange: (order: CuttingProductionOrder | null) => void;
  inputId: string;
}) {
  const { t } = useT();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, size, setSize, isLoading, isValidating } = useSWRInfinite<OrderPage>(
    (index, previous) => previous && !previous.has_more ? null
      : `/api/production-orders?cutting_department_code=${cuttingDepartment}&page=${index + 1}&page_size=50&include_total=true&q=${encodeURIComponent(query)}`,
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const orders = useMemo(() => {
    const byId = new Map<number, CuttingProductionOrder>();
    if (selectedOrder?.id === Number(value)) byId.set(selectedOrder.id, selectedOrder);
    for (const page of data || []) for (const order of page.rows) byId.set(order.id, order);
    return byId;
  }, [data, selectedOrder, value]);
  const options = useMemo(() => [
    { value: 0, label: t("page.cuttingPassports.placeholder.chooseNone") },
    ...Array.from(orders.values()).map((order) => ({
      value: order.id,
      label: `${orderReference(order, order.production_no)}${order.model_code ? ` · ${order.model_code}` : ""}`,
      searchText: order.production_no,
    })),
  ], [orders, t]);

  return <SearchableSelect
    inputId={inputId}
    value={Number(value || 0)}
    options={options}
    onChange={(orderId) => onChange(Number(orderId) ? orders.get(Number(orderId)) || null : null)}
    placeholder={t("page.cuttingPassports.placeholder.chooseNone")}
    noResultsText={t("page.search.noMatches")}
    loadingText={t("common.loading")}
    loadMoreText={t("common.loadMore")}
    loading={isLoading || isValidating}
    hasMore={Boolean(data?.at(-1)?.has_more)}
    onSearchChange={setSearch}
    onLoadMore={() => void setSize(size + 1)}
    serverFilter
  />;
}
