"use client";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Download, Filter, MoreHorizontal, Plus, Search, X } from "lucide-react";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

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
  const searchParams = useSearchParams();
  const initialQ = searchParams.get("q") || "";

  const { data = [], isLoading } = useSWR<SO[]>("/api/sales-orders", fetcher);
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [showFilters, setShowFilters] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [query, setQuery] = useState(initialQ);

  useEffect(() => {
    setQuery(initialQ);
  }, [initialQ]);

  const customerMap = new Map(customers.map((c) => [c.id, c.name]));

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
    { key: "all" as TabKey, label: "All", count: data.length },
    { key: "production" as TabKey, label: "In production", count: data.filter((o) => ["production", "planning", "confirmed"].includes(o.status)).length },
    { key: "late" as TabKey, label: "Late", count: data.filter((o) => o.status === "late").length },
    { key: "shipping" as TabKey, label: "Shipping", count: data.filter((o) => o.status === "ready").length },
    { key: "draft" as TabKey, label: "Draft", count: data.filter((o) => o.status === "draft").length },
  ], [data]);

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

  return (
    <div>
      <PageHeader
        eyebrow="Commerce / Sales orders"
        title="Sales orders"
        subtitle={`${activeCount} active · $${Math.round(inFlight).toLocaleString()} in flight · ${filtered.length} shown`}
        actions={(
          <>
            <button className="btn" onClick={() => setShowFilters((v) => !v)}><Filter />Filter</button>
            <button className="btn" onClick={exportCsv} disabled={!filtered.length}><Download />Export</button>
            <a href="/sales-orders/new" className="btn btn-primary"><Plus />New order</a>
          </>
        )}
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex h-9 min-w-[280px] flex-1 items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3">
          <Search className="h-4 w-4 text-[#8a8472]" />
          <input
            className="w-full bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
            placeholder="Search order number, customer, status..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query ? (
            <button className="icon-btn" onClick={() => setQuery("")} title="Clear search"><X /></button>
          ) : null}
        </div>
      </div>

      {showFilters ? (
        <div className="card mb-4 grid grid-cols-1 gap-3 p-4 md:grid-cols-2">
          <div>
            <label className="label">Status</label>
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="all">All statuses</option>
              {[...new Set(data.map((o) => o.status))].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Order type</label>
            <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="all">All types</option>
              <option value="client_order">client_order</option>
              <option value="branded_stock_sale">branded_stock_sale</option>
            </select>
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

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_480px]">
        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th className="w-10"><input type="checkbox" /></th>
                <th>Order</th>
                <th>Customer</th>
                <th>Qty</th>
                <th>Progress</th>
                <th>Stage</th>
                <th>Due</th>
                <th className="text-right">Value</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && <tr><td colSpan={8} className="text-[#8a8472]">Loading...</td></tr>}
              {!isLoading && !filtered.length && <tr><td colSpan={8} className="text-[#8a8472]">No orders match the current filters.</td></tr>}
              {filtered.map((o, i) => {
                const pct = [62, 18, 81, 47, 4, 0, 93, 100][i % 8];
                const qty = [4800, 12000, 3200, 9600, 2100, 1500, 5400, 720][i % 8];
                const active = selected?.id === o.id;
                return (
                  <tr key={o.id} data-selected={active} className={active ? "bg-[#fdf3eb]" : ""} onClick={() => setSelectedId(o.id)}>
                    <td><input type="checkbox" onClick={(e) => e.stopPropagation()} /></td>
                    <td><a href={`/sales-orders/${o.id}`} className="mono font-medium">{o.order_no}</a></td>
                    <td>{customerMap.get(o.customer_id) ?? "Unknown customer"}</td>
                    <td className="mono text-right">{qty.toLocaleString()}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="mini-bar w-24"><span style={{ width: `${pct}%` }} /></div>
                        <span className="mono text-xs text-[#8a8472]">{pct}%</span>
                      </div>
                    </td>
                    <td><span className={`badge ${statusClass(o.status)}`}>{o.status}</span></td>
                    <td className="mono text-[#8a8472]">{o.deadline ? new Date(o.deadline).toLocaleDateString("en-US", { month: "short", day: "2-digit" }) : "-"}</td>
                    <td className="text-right"><Money value={Number(o.total_amount || 0)} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <aside className="card self-start">
          {selected ? (
            <>
              <div className="flex items-center justify-between border-b border-[#ecebe3] px-4 py-4">
                <a href={`/sales-orders/${selected.id}`} className="mono font-semibold">{selected.order_no}</a>
                <div className="flex items-center gap-3">
                  <span className={`badge ${statusClass(selected.status)}`}>{selected.status}</span>
                  <button className="icon-btn"><MoreHorizontal /></button>
                </div>
              </div>
              <div className="space-y-6 p-4">
                <section>
                  <div className="label">Customer</div>
                  <div className="text-lg font-semibold">{customerMap.get(selected.customer_id) ?? "Unknown customer"}</div>
                </section>
                <section>
                  <div className="label">Order type</div>
                  <div className="badge">{selected.order_type}</div>
                </section>
                <section>
                  <div className="label">Financials</div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between"><span>Subtotal</span><Money value={Number(selected.total_amount || 0)} /></div>
                    <div className="flex justify-between"><span>Tax (12%)</span><Money value={Number(selected.total_amount || 0) * 0.12} /></div>
                    <div className="flex justify-between border-t border-[#ecebe3] pt-2"><span>Total</span><Money value={Number(selected.total_amount || 0) * 1.12} /></div>
                  </div>
                </section>
              </div>
            </>
          ) : (
            <div className="p-6 text-sm text-[#8a8472]">Select an order to inspect it.</div>
          )}
        </aside>
      </div>
    </div>
  );
}

