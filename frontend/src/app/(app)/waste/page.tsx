"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function WastePage() {
  const { t } = useT();
  const { data, mutate } = useSWR<any[]>("/api/waste", fetcher);
  const { data: items } = useSWR<any[]>("/api/inventory/items?category=waste", fetcher);
  const { data: depts } = useSWR<any[]>("/api/departments", fetcher);
  const { data: dash } = useSWR<any>("/api/dashboard/waste", fetcher);
  const [f, setF] = useState({ item_id: 0, source_department_id: 0, waste_type: "fabric", quantity: 0, unit: "kg", reason: "", sellable: true, estimated_value: 0 });
  const [msg, setMsg] = useState("");

  async function record(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try { await api.post("/api/waste", f); mutate(); setMsg(t("msg.recorded")); }
    catch (e: any) { setMsg(e.message); }
  }
  async function act(id: number, action: string, body?: any) {
    await api.post(`/api/waste/${id}/${action}`, body); mutate();
  }

  return (
    <div>
      <PageHeader title={t("page.waste.title")} />
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.waste.sellable")}</div><div className="text-2xl font-semibold">{dash?.sellable_count ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.waste.nonSellable")}</div><div className="text-2xl font-semibold">{dash?.non_sellable_count ?? 0}</div></div>
      </div>
      <form onSubmit={record} className="card p-4 mb-6 grid grid-cols-1 md:grid-cols-4 gap-3">
        <select className="input" value={f.item_id} onChange={(e) => setF({ ...f, item_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.item")}</option>{items?.map((i) => <option key={i.id} value={i.id}>{i.sku} — {i.name}</option>)}
        </select>
        <select className="input" value={f.source_department_id} onChange={(e) => setF({ ...f, source_department_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.sourceDept")}</option>{depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <input className="input" placeholder={t("page.waste.wasteType")} value={f.waste_type} onChange={(e) => setF({ ...f, waste_type: e.target.value })} />
        <input className="input" type="number" step="0.01" placeholder={t("field.quantity")} value={f.quantity} onChange={(e) => setF({ ...f, quantity: Number(e.target.value) })} />
        <input className="input" placeholder={t("field.unit")} value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} />
        <input className="input" type="number" step="0.01" placeholder={t("field.estimatedValue")} value={f.estimated_value} onChange={(e) => setF({ ...f, estimated_value: Number(e.target.value) })} />
        <label className="text-sm flex items-center gap-2 mt-1"><input type="checkbox" checked={f.sellable} onChange={(e) => setF({ ...f, sellable: e.target.checked })} />{t("field.sellable")}</label>
        <button className="btn btn-primary md:col-span-1">{t("btn.recordWaste")}</button>
        {msg && <div className="md:col-span-4 text-sm">{msg}</div>}
      </form>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.wasteType")}</th><th>{t("field.qty")}</th><th>{t("field.sellable")}</th>
              <th>{t("field.status")}</th><th>{t("field.value")}</th><th></th>
            </tr>
          </thead>
          <tbody>
            {data?.map((w) => (
              <tr key={w.id}>
                <td>{w.waste_type}</td>
                <td>{Number(w.quantity).toFixed(2)} {w.unit}</td>
                <td>{w.sellable ? t("field.yes") : t("field.no")}</td>
                <td><span className="badge">{w.status}</span></td>
                <td>${Number(w.estimated_value).toFixed(2)}</td>
                <td className="flex gap-2 flex-wrap">
                  {w.status === "recorded" && <button className="text-brand-600 hover:underline" onClick={() => act(w.id, "receive")}>{t("btn.receive")}</button>}
                  {w.status === "received_by_waste_department" && w.sellable && <button className="text-green-700 hover:underline" onClick={() => act(w.id, "sell", { buyer_name: "Buyer", quantity: w.quantity, unit_price: 0.1 })}>{t("page.waste.sellPrice")}</button>}
                  {w.status === "received_by_waste_department" && !w.sellable && <button className="text-yellow-700 hover:underline" onClick={() => act(w.id, "request-disposal", { reason: "Standard disposal" })}>{t("btn.requestDisposal")}</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
