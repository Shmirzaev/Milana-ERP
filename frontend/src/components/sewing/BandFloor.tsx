"use client";
import { useState } from "react";
import useSWR from "swr";
import DepartmentOrderList, { type DepartmentOrder } from "@/components/DepartmentOrderList";
import PageHeader from "@/components/PageHeader";
import { fetcher } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

export default function BandFloor() {
  const { t } = useT(); const { me } = useMe(); const [search, setSearch] = useState("");
  const { data, error } = useSWR<DepartmentOrder[]>("/api/sewing-bands/orders", fetcher, { refreshInterval: 10000 });
  const rows = (data || []).filter(row => !search || [row.order_no, row.production_no, row.model_no, row.variant_no, row.model_name].join(" ").toLowerCase().includes(search.toLowerCase()));
  return <div>
    <PageHeader title={t("page.deptInbox.title", { dept: t("nav.ecoCottonSewing") })} subtitle={me?.name} />
    <div className="mb-4"><input type="search" className="input max-w-xl" aria-label={t("common.search")} placeholder={t("common.search")} value={search} onChange={e => setSearch(e.target.value)} /></div>
    {error && <p role="alert" className="text-sm text-red-700">{String(error)}</p>}
    {!data && !error ? <div className="card p-4">{t("common.loading")}</div> : <DepartmentOrderList rows={rows} title={t("page.deptInbox.orders", { count: rows.length })} emptyLabel={t("page.deptInbox.noOrders")} t={t} orderHref={row => `/work-orders/${row.work_order_id}/sewing?assignment=${row.sewing_assignment_id}`} />}
  </div>;
}
