"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { Download, Filter, MoreHorizontal, Plus } from "lucide-react";
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

export default function SalesOrdersPage() {
  const { data = [], isLoading } = useSWR<SO[]>("/api/sales-orders", fetcher);
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const customerMap = new Map(customers.map((c) => [c.id, c.name]));
  const selected = data.find((o) => o.id === (selectedId ?? data[0]?.id)) ?? data[0];
  const activeCount = data.filter((o) => !["closed", "cancelled", "delivered"].includes(o.status)).length;
  const inFlight = data.reduce((s, o) => s + Number(o.total_amount || 0), 0);
  const tabs = useMemo(() => [
    ["All", data.length],
    ["In production", data.filter((o) => ["production", "planning", "confirmed"].includes(o.status)).length],
    ["Late", data.filter((o) => o.status === "late").length],
    ["Shipping", data.filter((o) => o.status === "ready").length],
    ["Draft", data.filter((o) => o.status === "draft").length],
  ], [data]);

  return (
    <div>
      <PageHeader
        eyebrow="Commerce / Sales orders"
        title="Sales orders"
        subtitle={`${activeCount} active · $${Math.round(inFlight).toLocaleString()} in flight · 4 due this week`}
        actions={(
          <>
            <button className="btn"><Filter />Filter</button>
            <button className="btn"><Download />Export</button>
            <a href="/sales-orders/new" className="btn btn-primary"><Plus />New order</a>
          </>
        )}
      />

      <div className="tab-row mb-4">
        {tabs.map(([label, count], i) => (
          <button key={String(label)} data-active={i === 0}>
            {label} <span className="ml-1 rounded-full bg-[#f1efe8] px-1.5 text-[11px] text-[#8a8472]">{count}</span>
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
              {data.map((o, i) => {
                const pct = [62, 18, 81, 47, 4, 0, 93, 100][i % 8];
                const qty = [4800, 12000, 3200, 9600, 2100, 1500, 5400, 720][i % 8];
                const active = selected?.id === o.id;
                return (
                  <tr key={o.id} data-selected={active} className={active ? "bg-[#fdf3eb]" : ""} onClick={() => setSelectedId(o.id)}>
                    <td><input type="checkbox" onClick={(e) => e.stopPropagation()} /></td>
                    <td><a href={`/sales-orders/${o.id}`} className="mono font-medium">{o.order_no}</a></td>
                    <td>{customerMap.get(o.customer_id) ?? "ZARA Tashkent"}</td>
                    <td className="mono text-right">{qty.toLocaleString()}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="mini-bar w-24"><span style={{ width: `${pct}%` }} /></div>
                        <span className="mono text-xs text-[#8a8472]">{pct}%</span>
                      </div>
                    </td>
                    <td><span className={`badge ${statusClass(o.status)}`}>{o.status}</span></td>
                    <td className="mono text-[#8a8472]">{o.deadline ? new Date(o.deadline).toLocaleDateString("en-US", { month: "short", day: "2-digit" }) : "May 28"}</td>
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
              <div className="space-y-7 p-4">
                <section>
                  <div className="label">Customer</div>
                  <div className="text-lg font-semibold">{customerMap.get(selected.customer_id) ?? "ZARA Tashkent"}</div>
                </section>
                <section>
                  <div className="mb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                    <div className="h-px bg-[#ecebe3]" />
                    <div className="label mb-0">Lines</div>
                    <div className="h-px bg-[#ecebe3]" />
                  </div>
                  <div className="flex items-center gap-3 rounded-lg bg-[#f1efe8] p-3">
                    <div className="grid h-20 w-20 place-items-center rounded-md bg-[repeating-linear-gradient(135deg,#ecebe3_0_10px,#f7f6f1_10px_20px)] text-xs text-[#8a8472]">TEE</div>
                    <div>
                      <div className="font-semibold">M-2204 Crew neck tee</div>
                      <div className="mt-1 text-sm text-[#8a8472]">Cotton jersey 220 gsm · 3 colors · 5 sizes</div>
                      <div className="mt-2 text-sm"><span className="mono font-semibold">4,800 pcs</span> <span className="text-[#8a8472]">· avg $18.00/pc</span></div>
                    </div>
                  </div>
                </section>
                <section>
                  <div className="mb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                    <div className="h-px bg-[#ecebe3]" />
                    <div className="label mb-0">Progress</div>
                    <div className="h-px bg-[#ecebe3]" />
                  </div>
                  <div className="mb-3 text-sm font-semibold">62%</div>
                  <div className="grid grid-cols-4 rounded-lg border border-[#e3dfd3]">
                    {[
                      ["Cut", "4 800"],
                      ["Print", "4 640"],
                      ["Sew", "2 960"],
                      ["Pack", "0"],
                    ].map(([k, v]) => (
                      <div key={k} className="border-r border-[#e3dfd3] p-3 last:border-r-0">
                        <div className="label">{k}</div>
                        <div className="mono font-semibold">{v}</div>
                      </div>
                    ))}
                  </div>
                </section>
                <section>
                  <div className="mb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                    <div className="h-px bg-[#ecebe3]" />
                    <div className="label mb-0">Schedule</div>
                    <div className="h-px bg-[#ecebe3]" />
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    {["Created May 02", "Start May 06", selected.deadline ? `Due ${new Date(selected.deadline).toLocaleDateString("en-US", { month: "short", day: "2-digit" })}` : "Due May 28"].map((x) => (
                      <div key={x} className="rounded-md bg-[#f1efe8] p-3">
                        <div className="label">{x.split(" ")[0]}</div>
                        <div className="mono text-sm font-semibold">{x.split(" ").slice(1).join(" ")}</div>
                      </div>
                    ))}
                  </div>
                </section>
                <section>
                  <div className="mb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                    <div className="h-px bg-[#ecebe3]" />
                    <div className="label mb-0">Financials</div>
                    <div className="h-px bg-[#ecebe3]" />
                  </div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between"><span>Subtotal</span><Money value={Number(selected.total_amount || 0)} /></div>
                    <div className="flex justify-between"><span>Tax (12%)</span><Money value={Number(selected.total_amount || 0) * 0.12} /></div>
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
