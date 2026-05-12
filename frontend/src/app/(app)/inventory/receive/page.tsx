"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function ReceiveStockPage() {
  const { t } = useT();
  const { data: items } = useSWR<any[]>("/api/inventory/items", fetcher);
  const { data: warehouses } = useSWR<any[]>("/api/inventory/warehouses", fetcher);
  const { data: suppliers } = useSWR<any[]>("/api/suppliers", fetcher);
  const [f, setF] = useState({
    item_id: 0, batch_no: "", supplier_id: 0, color: "", width: 0, gsm: 0,
    quantity: 0, unit: "meter", cost_per_unit: 0, warehouse_id: 0, qc_status: "passed",
  });
  const [msg, setMsg] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      const payload: any = { ...f, supplier_id: f.supplier_id || null };
      await api.post("/api/inventory/receive", payload);
      setMsg(t("msg.recorded"));
    } catch (e: any) { setMsg(e.message); }
  }
  return (
    <div>
      <PageHeader title={t("page.receiveStock.title")} subtitle={t("page.receiveStock.subtitle")} />
      <form onSubmit={submit} className="card p-6 grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl">
        <select className="input" value={f.item_id} onChange={(e) => setF({ ...f, item_id: Number(e.target.value) })} required>
          <option value={0}>{t("ph.item")}</option>
          {items?.map((i) => <option key={i.id} value={i.id}>{i.sku} — {i.name}</option>)}
        </select>
        <input className="input" placeholder={t("ph.batchNo")} value={f.batch_no} onChange={(e) => setF({ ...f, batch_no: e.target.value })} required />
        <select className="input" value={f.supplier_id} onChange={(e) => setF({ ...f, supplier_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.supplier")}</option>
          {suppliers?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <input className="input" placeholder={t("field.color")} value={f.color} onChange={(e) => setF({ ...f, color: e.target.value })} />
        <input className="input" type="number" placeholder={t("common.unit")} value={f.width} onChange={(e) => setF({ ...f, width: Number(e.target.value) })} />
        <input className="input" type="number" placeholder="GSM" value={f.gsm} onChange={(e) => setF({ ...f, gsm: Number(e.target.value) })} />
        <input className="input" type="number" step="0.01" placeholder={t("field.quantity")} value={f.quantity} onChange={(e) => setF({ ...f, quantity: Number(e.target.value) })} required />
        <input className="input" placeholder={t("field.unit")} value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} />
        <input className="input" type="number" step="0.01" placeholder={t("field.cost") + " / " + t("field.unit")} value={f.cost_per_unit} onChange={(e) => setF({ ...f, cost_per_unit: Number(e.target.value) })} />
        <select className="input" value={f.warehouse_id} onChange={(e) => setF({ ...f, warehouse_id: Number(e.target.value) })} required>
          <option value={0}>{t("ph.warehouse")}</option>
          {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
        <select className="input" value={f.qc_status} onChange={(e) => setF({ ...f, qc_status: e.target.value })}>
          <option value="pending">{t("qc.pending")}</option>
          <option value="passed">{t("qc.passed")}</option>
          <option value="failed">{t("qc.failed")}</option>
        </select>
        <button className="btn btn-primary md:col-span-3">{t("btn.receive")}</button>
        {msg && <div className="text-sm md:col-span-3">{msg}</div>}
      </form>
    </div>
  );
}
