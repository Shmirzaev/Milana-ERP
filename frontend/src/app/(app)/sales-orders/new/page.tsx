"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type Line = { model_id: number; color: string; size: string; quantity: number; unit_price: number; printing_required: boolean };

export default function NewSalesOrderPage() {
  const router = useRouter();
  const { t } = useT();
  const { data: customers } = useSWR<any[]>("/api/customers", fetcher);
  const { data: models } = useSWR<any[]>("/api/models", fetcher);
  const [customerId, setCustomerId] = useState<number | "">("");
  const [orderType, setOrderType] = useState("client_order");
  const [deadline, setDeadline] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([
    { model_id: 0, color: "white", size: "M", quantity: 50, unit_price: 12, printing_required: false },
  ]);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  function update(i: number, patch: Partial<Line>) {
    setLines(lines.map((l, j) => (i === j ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines([...lines, { model_id: 0, color: "white", size: "M", quantity: 1, unit_price: 0, printing_required: false }]);
  }
  function removeLine(i: number) { setLines(lines.filter((_, j) => j !== i)); }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setSaving(true);
    try {
      const payload: any = {
        customer_id: customerId || null,
        order_type: orderType,
        deadline: deadline || null,
        notes,
        items: lines,
      };
      const so = await api.post("/api/sales-orders", payload);
      router.push(`/sales-orders/${so.id}`);
    } catch (e: any) {
      setErr(e.message);
    } finally { setSaving(false); }
  }

  return (
    <div>
      <PageHeader title={t("page.newSO.title")} />
      <form onSubmit={submit} className="card p-6 space-y-5 max-w-4xl">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="label">{t("page.newSO.orderType")}</label>
            <select className="input" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
              <option value="client_order">{t("orderType.client")}</option>
              <option value="branded_stock_sale">{t("orderType.branded")}</option>
            </select>
          </div>
          <div>
            <label className="label">{t("field.customer")}</label>
            <select className="input" value={customerId} onChange={(e) => setCustomerId(Number(e.target.value) || "")}>
              <option value="">—</option>
              {customers?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t("field.deadline")}</label>
            <input className="input" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
          </div>
        </div>

        <div>
          <div className="flex justify-between items-center mb-2">
            <h2 className="font-medium">{t("page.newSO.lines")}</h2>
            <button type="button" className="btn" onClick={addLine}>{t("btn.addLine")}</button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.model")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th>
                <th>{t("field.qty")}</th><th>{t("field.unitPrice")}</th><th>{t("field.printingRequired")}</th><th></th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i}>
                  <td>
                    <select className="input" value={l.model_id} onChange={(e) => update(i, { model_id: Number(e.target.value) })}>
                      <option value={0}>—</option>
                      {models?.map((m) => <option key={m.id} value={m.id}>{m.code} — {m.name}</option>)}
                    </select>
                  </td>
                  <td><input className="input" value={l.color} onChange={(e) => update(i, { color: e.target.value })} /></td>
                  <td><input className="input" value={l.size} onChange={(e) => update(i, { size: e.target.value })} /></td>
                  <td><input className="input" type="number" value={l.quantity} onChange={(e) => update(i, { quantity: Number(e.target.value) })} /></td>
                  <td><input className="input" type="number" step="0.01" value={l.unit_price} onChange={(e) => update(i, { unit_price: Number(e.target.value) })} /></td>
                  <td><input type="checkbox" checked={l.printing_required} onChange={(e) => update(i, { printing_required: e.target.checked })} /></td>
                  <td><button type="button" className="btn btn-danger" onClick={() => removeLine(i)}>{t("btn.remove")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <label className="label">{t("field.notes")}</label>
          <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {err && <div className="text-sm text-red-600">{err}</div>}
        <button className="btn btn-primary" disabled={saving}>{saving ? t("common.loading") : t("btn.createOrder")}</button>
      </form>
    </div>
  );
}
