"use client";
import { useState } from "react";
import useSWR from "swr";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type Line = { model_id: number; color: string; size: string; quantity: number; unit_price: number; printing_required: boolean };

export default function NewSalesOrderPage() {
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
  function removeLine(i: number) {
    setLines(lines.length === 1 ? lines : lines.filter((_, j) => j !== i));
  }

  const subtotal = lines.reduce((s, l) => s + Number(l.quantity || 0) * Number(l.unit_price || 0), 0);
  const qty = lines.reduce((s, l) => s + Number(l.quantity || 0), 0);

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
      window.location.href = `/sales-orders/${so.id}`;
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow={t("newso.eyebrow")}
        title={t("newso.title")}
        subtitle={t("newso.subtitle")}
        actions={<a href="/sales-orders" className="btn"><ArrowLeft />{t("newso.backToOrders")}</a>}
      />

      <form onSubmit={submit} className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <section className="card p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="app-card-title">{t("newso.orderDetails")}</h2>
                <p className="mt-1 text-sm text-[#8a8472]">{t("newso.orderDetailsSub")}</p>
              </div>
              <span className="badge bg-[#fbe9dd] text-[#c2410c]">{t("newso.draft")}</span>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div>
                <label className="label">{t("sales.orderType")}</label>
                <select className="input" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
                  <option value="client_order">{t("orderType.client")}</option>
                  <option value="branded_stock_sale">{t("orderType.branded")}</option>
                </select>
              </div>
              <div>
                <label className="label">{t("field.customer")}</label>
                <select className="input" value={customerId} onChange={(e) => setCustomerId(Number(e.target.value) || "") }>
                  <option value="">{t("newso.customerSelect")}</option>
                  {customers?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label">{t("field.deadline")}</label>
                <input className="input" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
              </div>
            </div>
          </section>

          <section className="card">
            <div className="flex items-center justify-between border-b border-[#ecebe3] px-5 py-4">
              <div>
                <h2 className="app-card-title">{t("newso.lines")}</h2>
                <p className="mt-1 text-sm text-[#8a8472]">{t("newso.linesSummary", { lines: lines.length, qty: qty.toLocaleString() })}</p>
              </div>
              <button type="button" className="btn" onClick={addLine}><Plus />{t("newso.addLine")}</button>
            </div>
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("field.model")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th><th>{t("field.qty")}</th><th>{t("field.unitPrice")}</th><th>{t("field.printingRequired")}</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => (
                    <tr key={i}>
                      <td className="min-w-72">
                        <select className="input" value={l.model_id} onChange={(e) => update(i, { model_id: Number(e.target.value) })}>
                          <option value={0}>{t("newso.selectModel")}</option>
                          {models?.map((m) => <option key={m.id} value={m.id}>{m.code} - {m.name}</option>)}
                        </select>
                      </td>
                      <td><input className="input min-w-28" value={l.color} onChange={(e) => update(i, { color: e.target.value })} /></td>
                      <td><input className="input w-24" value={l.size} onChange={(e) => update(i, { size: e.target.value })} /></td>
                      <td><input className="input w-28" type="number" value={l.quantity} onChange={(e) => update(i, { quantity: Number(e.target.value) })} /></td>
                      <td><input className="input w-32" type="number" step="0.01" value={l.unit_price} onChange={(e) => update(i, { unit_price: Number(e.target.value) })} /></td>
                      <td><input type="checkbox" checked={l.printing_required} onChange={(e) => update(i, { printing_required: e.target.checked })} /></td>
                      <td>
                        <button type="button" className="icon-btn text-red-600" onClick={() => removeLine(i)} title={t("newso.remove")}>
                          <Trash2 />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card p-5">
            <label className="label">{t("field.notes")}</label>
            <textarea className="input" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("newso.notesPlaceholder")} />
          </section>
        </div>

        <aside className="card self-start">
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <h2 className="app-card-title">{t("newso.orderSummary")}</h2>
            <p className="mt-1 text-sm text-[#8a8472]">{t("newso.orderSummarySub")}</p>
          </div>
          <div className="space-y-5 p-5">
            <div className="rounded-lg bg-[#f1efe8] p-4">
              <div className="label">{t("newso.totalQuantity")}</div>
              <div className="mt-1 text-3xl font-semibold">{qty.toLocaleString()}</div>
              <div className="mt-1 text-sm text-[#8a8472]">{t("newso.piecesAcross", { qty: qty.toLocaleString(), lines: lines.length })}</div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-[#8a8472]">{t("sales.subtotal")}</span><span className="mono">${subtotal.toFixed(2)}</span></div>
              <div className="flex justify-between"><span className="text-[#8a8472]">{t("newso.estimatedTax")}</span><span className="mono">${(subtotal * 0.12).toFixed(2)}</span></div>
              <div className="border-t border-[#ecebe3] pt-3 flex justify-between text-base font-semibold"><span>{t("common.total")}</span><span className="mono">${(subtotal * 1.12).toFixed(2)}</span></div>
            </div>
            {err && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{err}</div>}
            <button className="btn btn-primary w-full" disabled={saving}>{saving ? t("newso.creating") : t("newso.createOrder")}</button>
            <p className="text-xs text-[#8a8472]">{t("newso.afterCreate")}</p>
          </div>
        </aside>
      </form>
    </div>
  );
}
