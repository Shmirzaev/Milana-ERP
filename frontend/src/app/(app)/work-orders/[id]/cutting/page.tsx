"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { operationLabel, statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

type BundlePlan = { color: string; size: string; quantity: number; count: number; next: "sewing" | "printing" };

export default function CuttingPage() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data: wo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: po } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: model } = useSWR<any>(po?.model_id ? `/api/models/${po.model_id}` : null, fetcher);
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);
  const { data: batches } = useSWR<any[]>("/api/inventory/batches", fetcher);
  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);
  const orderQtyByKey = useMemo(() => {
    const map = new Map<string, number>();
    for (const it of po?.items || []) {
      const key = `${String(it?.color || "").trim().toLowerCase()}||${String(it?.size || "").trim().toLowerCase()}`;
      map.set(key, Number(it?.planned_quantity || 0));
    }
    return map;
  }, [po?.items]);

  const [form, setForm] = useState({
    fabric_batch_id: 0,
    input_quantity: 0,
    input_unit: "kg",
    cut_pieces: 0,
    passed_pieces: 0,
    defective_pieces: 0,
    waste_quantity: 0,
    waste_unit: "kg",
    notes: "",
  });
  const [bundles, setBundles] = useState<BundlePlan[]>([]);
  const [bundlesAutofilled, setBundlesAutofilled] = useState(false);
  const [createdBundles, setCreatedBundles] = useState<any[]>([]);
  const [doneMsg, setDoneMsg] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (bundlesAutofilled) return;
    if (!Array.isArray(po?.items) || po.items.length === 0) return;
    const hasPrintingStage = Array.isArray(po?.work_orders) && po.work_orders.some((w: any) => w.operation === "printing");
    const nextStage: "sewing" | "printing" = hasPrintingStage ? "printing" : "sewing";
    const defaultBundleQty = 50;
    const prefilled = po.items
      .filter((it: any) => Number(it?.planned_quantity || 0) > 0)
      .map((it: any) => ({
        color: String(it?.color || "").trim() || "-",
        size: String(it?.size || "").trim() || "-",
        quantity: defaultBundleQty,
        count: Math.max(1, Math.ceil(Number(it?.planned_quantity || 0) / defaultBundleQty)),
        next: nextStage,
      }));
    if (prefilled.length > 0) {
      setBundles(prefilled);
      setBundlesAutofilled(true);
    }
  }, [po, bundlesAutofilled]);

  function setB(i: number, p: Partial<BundlePlan>) {
    setBundles(bundles.map((b, j) => (i === j ? { ...b, ...p } : b)));
  }
  function setBQty(i: number, nextQtyRaw: number) {
    const nextQty = Math.max(1, Number(nextQtyRaw || 0));
    setBundles((prev) => prev.map((b, j) => {
      if (i !== j) return b;
      const key = `${String(b.color || "").trim().toLowerCase()}||${String(b.size || "").trim().toLowerCase()}`;
      const targetQty = orderQtyByKey.get(key) ?? (Number(b.quantity || 0) * Number(b.count || 1));
      const nextCount = Math.max(1, Math.ceil(Number(targetQty || 0) / nextQty));
      return { ...b, quantity: nextQty, count: nextCount };
    }));
  }
  function addB() {
    const first = bundles[0];
    setBundles([
      ...bundles,
      {
        color: first?.color || "white",
        size: first?.size || "M",
        quantity: first?.quantity || 50,
        count: 1,
        next: first?.next || "sewing",
      },
    ]);
  }
  function remB(i: number) {
    setBundles(bundles.filter((_, j) => j !== i));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setDoneMsg("");
    setSubmitting(true);
    try {
      const r = await api.post("/api/cutting/records", {
        work_order_id: id,
        ...form,
        fabric_batch_id: form.fabric_batch_id || null,
        bundles,
      });
      const created = Array.isArray(r?.bundles) ? r.bundles : [];
      setCreatedBundles(created);
      setDoneMsg(t("msg.cuttingDone", { count: created.length }));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  function d(v?: string | null) {
    return v ? new Date(v).toLocaleDateString() : "-";
  }

  return (
    <div>
      <PageHeader
        title={t("page.cutting.title", { id })}
        subtitle={wo ? t("page.cutting.subtitle", { op: operationLabel(wo.operation, t), status: statusLabel(wo.status, t) }) : ""}
      />
      <div className="card mb-4 p-4">
        <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.shipments.salesOrder")}</div>
            <div className="font-medium">{so?.order_no || (po?.sales_order_id ? `#${po.sales_order_id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.customer")}</div>
            <div className="font-medium">{so?.customer_id ? (customerMap.get(so.customer_id) || `#${so.customer_id}`) : "-"}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.model")}</div>
            <div className="font-medium">{model ? `${model.code} - ${model.name}` : (po?.model_id ? `#${po.model_id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.productionOrder")}</div>
            <div className="font-medium">{po?.production_no || (po?.id ? `#${po.id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.plannedQty")}</div>
            <div className="font-medium">{po?.planned_quantity ?? wo?.planned_output_qty ?? 0}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("common.status")}</div>
            <div className="font-medium">{wo ? statusLabel(wo.status, t) : "-"}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.salesDeadline")}</div>
            <div className="font-medium">{d(so?.deadline)}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.poDeadline")}</div>
            <div className="font-medium">{d(po?.deadline)}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.woDeadline")}</div>
            <div className="font-medium">{d(wo?.deadline)}</div>
          </div>
        </div>
        {Array.isArray(po?.items) && po.items.length > 0 && (
          <div className="mt-3 border-t border-[#ecebe3] pt-3">
            <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">{t("page.workOrder.breakdown")}</div>
            <div className="flex flex-wrap gap-2">
              {po.items.map((it: any) => (
                <span key={it.id} className="rounded-full bg-[#f5f2e8] px-3 py-1 text-xs text-[#5d5747]">
                  {(it.color || "-")} / {(it.size || "-")} / {it.planned_quantity ?? 0}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      <form onSubmit={submit} className="card space-y-5 p-6">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div>
            <label className="label">{t("field.fabricBatch")}</label>
            <select className="input" value={form.fabric_batch_id} onChange={(e) => setForm({ ...form, fabric_batch_id: Number(e.target.value) })}>
              <option value={0}>-</option>
              {batches?.map((b) => <option key={b.id} value={b.id}>{b.batch_no} ({b.color || ""} {b.quantity}{b.unit})</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t("field.inputQty")}</label>
            <input className="input" type="number" step="0.01" value={form.input_quantity} onChange={(e) => setForm({ ...form, input_quantity: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.inputUnit")}</label>
            <input className="input" value={form.input_unit} onChange={(e) => setForm({ ...form, input_unit: e.target.value })} />
          </div>
          <div>
            <label className="label">{t("field.cutPieces")}</label>
            <input className="input" type="number" value={form.cut_pieces} onChange={(e) => setForm({ ...form, cut_pieces: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.passed")}</label>
            <input className="input" type="number" value={form.passed_pieces} onChange={(e) => setForm({ ...form, passed_pieces: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.defective")}</label>
            <input className="input" type="number" value={form.defective_pieces} onChange={(e) => setForm({ ...form, defective_pieces: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.wasteQty")}</label>
            <input className="input" type="number" step="0.01" value={form.waste_quantity} onChange={(e) => setForm({ ...form, waste_quantity: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.wasteUnit")}</label>
            <input className="input" value={form.waste_unit} onChange={(e) => setForm({ ...form, waste_unit: e.target.value })} />
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-medium">{t("page.cutting.bundlePlan")}</h3>
            <button type="button" className="btn" onClick={addB}>{t("btn.addBundleLine")}</button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.color")}</th>
                <th>{t("field.size")}</th>
                <th>{t("field.bundleQty")}</th>
                <th>{t("field.count")}</th>
                <th>{t("field.next")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {bundles.map((b, i) => (
                <tr key={i}>
                  <td><input className="input" value={b.color} onChange={(e) => setB(i, { color: e.target.value })} /></td>
                  <td><input className="input" value={b.size} onChange={(e) => setB(i, { size: e.target.value })} /></td>
                  <td><input className="input" type="number" value={b.quantity} onChange={(e) => setBQty(i, Number(e.target.value))} /></td>
                  <td><input className="input" type="number" value={b.count} onChange={(e) => setB(i, { count: Number(e.target.value) })} /></td>
                  <td>
                    <select className="input" value={b.next} onChange={(e) => setB(i, { next: e.target.value as any })}>
                      <option value="sewing">{t("page.cutting.toSewing")}</option>
                      <option value="printing">{t("page.cutting.toPrinting")}</option>
                    </select>
                  </td>
                  <td><button type="button" className="btn btn-danger" onClick={() => remB(i)}>{t("btn.remove")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <label className="label">{t("common.notes")}</label>
          <textarea className="input" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>

        {doneMsg && <div className="rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">{doneMsg}</div>}
        {err && <div className="text-sm text-red-600">{err}</div>}
        <button className="btn btn-primary" disabled={submitting}>
          {submitting ? t("msg.creatingBundles") : t("btn.saveCreateBundles")}
        </button>
      </form>

      {createdBundles.length > 0 && (
        <div className="card mt-6 p-4">
          <h3 className="mb-2 font-medium">{t("page.cutting.bundlesCreated")}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.bundleNo")}</th>
                <th>{t("field.barcode")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {createdBundles.map((b) => (
                <tr key={b.id}>
                  <td>{b.bundle_no}</td>
                  <td><code>{b.barcode}</code></td>
                  <td><button type="button" className="text-brand-600 hover:underline" onClick={() => api.openLabel(`/api/bundles/${b.id}/label`)}>{t("common.print")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
