"use client";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Download, Filter, MoreHorizontal, Plus, Search, X } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { useDialogs } from "@/components/DialogProvider";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";

type SO = {
  id: number;
  order_no: string;
  customer_id: number | null;
  order_type: string;
  status: string;
  deadline: string | null;
  total_amount: number;
  notes: string | null;
};

type TabKey = "all" | "production" | "late" | "shipping" | "draft";

function statusClass(status: string) {
  const s = status.toLowerCase();
  if (s.includes("late") || s.includes("cancel")) return "bg-red-100 text-red-700";
  if (s.includes("deliver") || s.includes("ship")) return "bg-green-100 text-green-700";
  if (s.includes("planning") || s.includes("confirm")) return "bg-blue-100 text-blue-700";
  return "bg-[#fbe9dd] text-[#c2410c]";
}

function Money({ value }: { value: number }) {
  return <span className="mono">${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>;
}

function rowMetrics(index: number) {
  return {
    pct: [62, 18, 81, 47, 4, 0, 93, 100][index % 8],
    qty: [4800, 12000, 3200, 9600, 2100, 1500, 5400, 720][index % 8],
  };
}

function toCsvCell(value: unknown): string {
  const s = String(value ?? "");
  if (s.includes(",") || s.includes("\n") || s.includes('"')) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function matchesTab(o: SO, tab: TabKey): boolean {
  if (tab === "all") return true;
  if (tab === "production") return ["production", "planning", "confirmed"].includes(o.status);
  if (tab === "late") return o.status === "late";
  if (tab === "shipping") return o.status === "ready";
  if (tab === "draft") return o.status === "draft";
  return true;
}

export default function SalesOrdersPage() {
  const { t } = useT();
  const dialogs = useDialogs();
  const searchParams = useSearchParams();
  const initialQ = searchParams.get("q") || "";

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [showFilters, setShowFilters] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [query, setQuery] = useState(initialQ);
  const salesUrl = useMemo(() => {
    const params = new URLSearchParams({
      include_total: "true",
      page: String(page),
      page_size: String(pageSize),
    });
    const trimmed = query.trim();
    if (trimmed) params.set("q", trimmed);
    if (statusFilter !== "all") params.set("status", statusFilter);
    if (typeFilter !== "all") params.set("order_type", typeFilter);
    if (createdFrom) params.set("created_from", createdFrom);
    if (createdTo) params.set("created_to", createdTo);
    return `/api/sales-orders?${params.toString()}`;
  }, [createdFrom, createdTo, page, pageSize, query, statusFilter, typeFilter]);
  const { data: pageData, isLoading, mutate } = useSWR<any>(
    salesUrl,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const data = useMemo<SO[]>(() => pageData?.rows || [], [pageData?.rows]);

  useEffect(() => {
    setQuery(initialQ);
  }, [initialQ]);

  useEffect(() => {
    setPage(1);
  }, [createdFrom, createdTo, query, statusFilter, typeFilter]);

  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return data.filter((o) => {
      if (!matchesTab(o, activeTab)) return false;
      if (statusFilter !== "all" && o.status !== statusFilter) return false;
      if (typeFilter !== "all" && o.order_type !== typeFilter) return false;
      if (!q) return true;
      const customer = String(customerMap.get(o.customer_id) || "").toLowerCase();
      return (
        o.order_no.toLowerCase().includes(q) ||
        o.status.toLowerCase().includes(q) ||
        o.order_type.toLowerCase().includes(q) ||
        customer.includes(q)
      );
    });
  }, [data, activeTab, statusFilter, typeFilter, query, customerMap]);

  const selected = filtered.find((o) => o.id === (selectedId ?? filtered[0]?.id)) ?? filtered[0];
  const activeCount = data.filter((o) => !["closed", "cancelled", "delivered"].includes(o.status)).length;
  const inFlight = data.reduce((s, o) => s + Number(o.total_amount || 0), 0);

  const tabs = useMemo(() => [
    { key: "all" as TabKey, label: t("sales.tab.all"), count: data.length },
    { key: "production" as TabKey, label: t("sales.tab.production"), count: data.filter((o) => ["production", "planning", "confirmed"].includes(o.status)).length },
    { key: "late" as TabKey, label: t("sales.tab.late"), count: data.filter((o) => o.status === "late").length },
    { key: "shipping" as TabKey, label: t("sales.tab.shipping"), count: data.filter((o) => o.status === "ready").length },
    { key: "draft" as TabKey, label: t("sales.tab.draft"), count: data.filter((o) => o.status === "draft").length },
  ], [data, t]);

  function exportCsv() {
    if (!filtered.length) return;
    const header = ["order_no", "customer", "order_type", "status", "deadline", "total_amount"];
    const lines = filtered.map((o) => [
      o.order_no,
      customerMap.get(o.customer_id) || "",
      o.order_type,
      o.status,
      o.deadline || "",
      Number(o.total_amount || 0).toFixed(2),
    ]);
    const csv = [header, ...lines].map((row) => row.map(toCsvCell).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sales-orders-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function removeSalesOrder(id: number, orderNo: string) {
    if (!(await dialogs.ask({ message: `${t("common.delete")} ${orderNo}?`, tone: "danger" }))) return;
    try {
      await api.del(`/api/sales-orders/${id}`);
      if (selectedId === id) setSelectedId(null);
      mutate();
    } catch (e: any) {
      await dialogs.notify(e.message);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow={t("sales.eyebrow")}
        title={t("sales.title")}
        subtitle={t("sales.subtitle", { active: activeCount, value: Math.round(inFlight).toLocaleString(), shown: filtered.length })}
        actions={(
          <>
            <button className="btn" onClick={() => setShowFilters((v) => !v)}><Filter />{t("sales.filter")}</button>
            <button className="btn" onClick={exportCsv} disabled={!filtered.length}><Download />{t("sales.export")}</button>
            <a href="/sales-orders/new" className="btn btn-primary"><Plus />{t("btn.newOrder").replace("+ ", "")}</a>
          </>
        )}
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex h-9 min-w-[280px] flex-1 items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3">
          <Search className="h-4 w-4 text-[#8a8472]" />
          <input
            className="w-full bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
            placeholder={t("sales.searchPlaceholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query ? (
            <button className="icon-btn" onClick={() => setQuery("")} title={t("sales.clearSearch")}><X /></button>
          ) : null}
        </div>
      </div>

      {showFilters ? (
        <div className="card mb-4 grid grid-cols-1 gap-3 p-4 md:grid-cols-4">
          <div>
            <label className="label">{t("common.status")}</label>
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="all">{t("sales.allStatuses")}</option>
              {[...new Set(data.map((o) => o.status))].map((s) => <option key={s} value={s}>{statusLabel(s, t)}</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t("sales.orderType")}</label>
            <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="all">{t("sales.allTypes")}</option>
              <option value="client_order">{t("orderType.client")}</option>
              <option value="branded_stock_sale">{t("orderType.branded")}</option>
            </select>
          </div>
          <div>
            <label className="label">{t("common.createdFrom")}</label>
            <input className="input" type="date" value={createdFrom} onChange={(e) => setCreatedFrom(e.target.value)} />
          </div>
          <div>
            <label className="label">{t("common.createdTo")}</label>
            <input className="input" type="date" value={createdTo} onChange={(e) => setCreatedTo(e.target.value)} />
          </div>
        </div>
      ) : null}

      <div className="tab-row mb-4">
        {tabs.map((tab) => (
          <button key={tab.key} data-active={activeTab === tab.key} onClick={() => setActiveTab(tab.key)}>
            {tab.label} <span className="ml-1 rounded-full bg-[#f1efe8] px-1.5 text-[11px] text-[#8a8472]">{tab.count}</span>
          </button>
        ))}
      </div>

      <div className="space-y-3 md:hidden">
        <div className="card divide-y divide-[#ecebe3]">
          {isLoading && <div className="p-4 text-sm text-[#8a8472]">{t("common.loading")}</div>}
          {!isLoading && !filtered.length && <div className="p-4 text-sm text-[#8a8472]">{t("sales.noMatch")}</div>}
          {filtered.map((o, i) => {
            const { pct, qty } = rowMetrics(i);
            return (
              <article key={o.id} className="p-4">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <a href={`/sales-orders/${o.id}`} className="mono block truncate font-semibold text-[#14110b]">
                      {o.order_no}
                    </a>
                    <div className="mt-1 truncate text-sm font-medium text-[#14110b]">
                      {customerMap.get(o.customer_id) ?? t("sales.unknownCustomer")}
                    </div>
                  </div>
                  <span className={`badge shrink-0 ${statusClass(o.status)}`}>{statusLabel(o.status, t)}</span>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="label">{t("field.qty")}</div>
                    <div className="mono font-semibold">{qty.toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="label">{t("field.value")}</div>
                    <div className="font-semibold"><Money value={Number(o.total_amount || 0)} /></div>
                  </div>
                  <div>
                    <div className="label">{t("field.deadline")}</div>
                    <div className="mono text-[#56503f]">
                      {o.deadline ? new Date(o.deadline).toLocaleDateString("en-US", { month: "short", day: "2-digit" }) : "-"}
                    </div>
                  </div>
                  <div>
                    <div className="label">{t("page.processes.progress")}</div>
                    <div className="flex items-center gap-2">
                      <div className="mini-bar flex-1"><span style={{ width: `${pct}%` }} /></div>
                      <span className="mono text-xs text-[#8a8472]">{pct}%</span>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
        <div className="card">
          <PaginationControls
            page={page}
            pageSize={pageSize}
            total={Number(pageData?.total || data.length)}
            count={data.length}
            onPageChange={setPage}
            onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
          />
        </div>
      </div>

      <div className="hidden grid-cols-1 gap-4 md:grid xl:grid-cols-[1.2fr_480px]">
        <div className="card">
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th className="w-10"><input type="checkbox" /></th>
                  <th>{t("field.orderNo")}</th>
                  <th>{t("field.customer")}</th>
                  <th>{t("field.qty")}</th>
                  <th>{t("page.processes.progress")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("field.deadline")}</th>
                  <th className="text-right">{t("field.value")}</th>
                </tr>
              </thead>
              <tbody>
                {isLoading && <tr><td colSpan={8} className="text-[#8a8472]">{t("common.loading")}</td></tr>}
                {!isLoading && !filtered.length && <tr><td colSpan={8} className="text-[#8a8472]">{t("sales.noMatch")}</td></tr>}
                {filtered.map((o, i) => {
                  const { pct, qty } = rowMetrics(i);
                  const active = selected?.id === o.id;
                  return (
                    <tr key={o.id} data-selected={active} className={active ? "bg-[#fdf3eb]" : ""} onClick={() => setSelectedId(o.id)}>
                      <td><input type="checkbox" onClick={(e) => e.stopPropagation()} /></td>
                      <td><a href={`/sales-orders/${o.id}`} className="mono font-medium">{o.order_no}</a></td>
                      <td>{customerMap.get(o.customer_id) ?? t("sales.unknownCustomer")}</td>
                      <td className="mono text-right">{qty.toLocaleString()}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="mini-bar w-24"><span style={{ width: `${pct}%` }} /></div>
                          <span className="mono text-xs text-[#8a8472]">{pct}%</span>
                        </div>
                      </td>
                      <td><span className={`badge ${statusClass(o.status)}`}>{statusLabel(o.status, t)}</span></td>
                      <td className="mono text-[#8a8472]">{o.deadline ? new Date(o.deadline).toLocaleDateString("en-US", { month: "short", day: "2-digit" }) : "-"}</td>
                      <td className="text-right"><Money value={Number(o.total_amount || 0)} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <PaginationControls
            page={page}
            pageSize={pageSize}
            total={Number(pageData?.total || data.length)}
            count={data.length}
            onPageChange={setPage}
            onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
          />
        </div>

        <aside className="card hidden self-start xl:block">
          {selected ? (
            <>
              <div className="flex items-center justify-between border-b border-[#ecebe3] px-4 py-4">
                <a href={`/sales-orders/${selected.id}`} className="mono font-semibold">{selected.order_no}</a>
                <div className="flex items-center gap-3">
                  <span className={`badge ${statusClass(selected.status)}`}>{statusLabel(selected.status, t)}</span>
                  <button className="icon-btn"><MoreHorizontal /></button>
                  <button
                    type="button"
                    className="text-xs text-red-600 hover:underline"
                    onClick={() => removeSalesOrder(selected.id, selected.order_no)}
                  >
                    {t("common.delete")}
                  </button>
                </div>
              </div>
              <div className="space-y-6 p-4">
                <section>
                  <div className="label">{t("field.customer")}</div>
                  <div className="text-lg font-semibold">{customerMap.get(selected.customer_id) ?? t("sales.unknownCustomer")}</div>
                </section>
                <section>
                  <div className="label">{t("sales.orderType")}</div>
                  <div className="badge">{selected.order_type === "client_order" ? t("orderType.client") : t("orderType.branded")}</div>
                </section>
                <section>
                  <div className="label">{t("sales.financials")}</div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between text-base font-semibold"><span>{t("field.totalAmount")}</span><Money value={Number(selected.total_amount || 0)} /></div>
                  </div>
                </section>
              </div>
            </>
          ) : (
            <div className="p-6 text-sm text-[#8a8472]">{t("sales.selectOrder")}</div>
          )}
        </aside>
      </div>
    </div>
  );
}
