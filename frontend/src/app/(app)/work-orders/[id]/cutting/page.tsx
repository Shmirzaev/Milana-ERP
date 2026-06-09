"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel, formatBatchSerial } from "@/lib/batchSerial";
import PageHeader from "@/components/PageHeader";
import { operationLabel, statusLabel } from "@/components/StagePipeline";
import WorkOrderProductInfo from "@/components/WorkOrderProductInfo";
import { useT } from "@/lib/i18n";

type BundlePlan = { color: string; size: string; quantity: number; count: number; next: "sewing" | "printing" };
type SplitRow = { name: string; planned_quantity: number; start_date: string; deadline: string; notes: string };

function itemKey(color: string, size: string) {
  return `${String(color || "").trim().toLowerCase()}||${String(size || "").trim().toLowerCase()}`;
}

function distributeBundleTargets(items: any[], totalQty: number): Map<string, number> {
  const rows = (items || [])
    .map((it: any, index: number) => ({
      index,
      color: String(it?.color || "").trim() || "-",
      size: String(it?.size || "").trim() || "-",
      planned: Math.max(0, Number(it?.planned_quantity || 0)),
      qty: 0,
      remainder: 0,
    }))
    .filter((it) => it.planned > 0);
  const targetTotal = Math.max(0, Math.floor(Number(totalQty || 0)));
  const plannedTotal = rows.reduce((sum, it) => sum + it.planned, 0);
  const out = new Map<string, number>();
  if (rows.length === 0 || plannedTotal <= 0 || targetTotal <= 0) return out;

  let used = 0;
  for (const row of rows) {
    const exact = (targetTotal * row.planned) / plannedTotal;
    row.qty = Math.floor(exact);
    row.remainder = exact - row.qty;
    used += row.qty;
  }
  let left = targetTotal - used;
  const ranked = [...rows].sort((a, b) => b.remainder - a.remainder || a.index - b.index);
  for (let i = 0; i < left; i += 1) {
    ranked[i % ranked.length].qty += 1;
  }
  for (const row of rows) out.set(itemKey(row.color, row.size), row.qty);
  return out;
}

function autoSplitRows(totalQty: number, maxPerBatch: number): SplitRow[] {
  const safeTotal = Math.max(0, Number(totalQty || 0));
  const safeMax = Math.max(1, Number(maxPerBatch || 1));
  if (safeTotal <= 0) return [{ name: "Batch 1", planned_quantity: 0, start_date: "", deadline: "", notes: "" }];
  const rows: SplitRow[] = [];
  let left = safeTotal;
  let idx = 1;
  while (left > 0) {
    const qty = Math.min(safeMax, left);
    rows.push({ name: `Batch ${idx}`, planned_quantity: qty, start_date: "", deadline: "", notes: "" });
    left -= qty;
    idx += 1;
  }
  return rows;
}

export default function CuttingPage() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data: wo, mutate: mutateWo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: po, mutate: mutatePo } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: model } = useSWR<any>(po?.model_id ? `/api/models/${po.model_id}` : null, fetcher);
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);
  const { data: batches } = useSWR<any[]>("/api/inventory/batches", fetcher);
  const { data: batchProgress, mutate: mutateBatchProgress } = useSWR<any>(
    wo ? `/api/work-orders/${id}/cutting-batch-progress` : null,
    fetcher,
  );
  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);

  const [form, setForm] = useState({
    production_batch_id: 0,
    fabric_batch_id: 0,
    input_quantity: 0,
    input_unit: "kg",
    cut_pieces: 0,
    waste_quantity: 0,
    waste_unit: "kg",
    notes: "",
  });
  const [bundles, setBundles] = useState<BundlePlan[]>([]);
  const [bundlesAutofilled, setBundlesAutofilled] = useState(false);
  const [createdBundles, setCreatedBundles] = useState<any[]>([]);
  const [createdBundlesExpanded, setCreatedBundlesExpanded] = useState(false);
  const [doneMsg, setDoneMsg] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");
  const [splitMax, setSplitMax] = useState(600);
  const [splitRows, setSplitRows] = useState<SplitRow[]>([]);
  const [splitBusy, setSplitBusy] = useState(false);
  const [splitErr, setSplitErr] = useState("");

  const plannedItemTotal = useMemo(
    () => (po?.items || []).reduce((sum: number, it: any) => sum + Math.max(0, Number(it?.planned_quantity || 0)), 0),
    [po?.items],
  );
  const bundleTargetTotal = Number(form.cut_pieces || 0) > 0 ? Number(form.cut_pieces || 0) : plannedItemTotal;
  const bundleTargetQtyByKey = useMemo(
    () => distributeBundleTargets(po?.items || [], bundleTargetTotal),
    [po?.items, bundleTargetTotal],
  );
  const isAlreadyBatched = Array.isArray(po?.batches) && po.batches.length > 0;
  const canSplitHere = Boolean(
    wo
    && po
    && !isAlreadyBatched
    && (wo.production_batch_id === null || wo.production_batch_id === undefined)
  );
  const splitTotal = splitRows.reduce((sum, row) => sum + Number(row.planned_quantity || 0), 0);
  const splitPlannedQty = Number(wo?.planned_output_qty || po?.planned_quantity || 0);
  const productInfoPo = useMemo(() => {
    if (!po || !canSplitHere || splitTotal <= splitPlannedQty) return po;
    return {
      ...po,
      actual_quantity: Math.max(Number(po?.actual_quantity || 0), splitTotal),
    };
  }, [canSplitHere, po, splitPlannedQty, splitTotal]);
  const batchItems = Array.isArray(batchProgress?.items) ? batchProgress.items : [];
  const createdBundlesBatch = useMemo(() => {
    const productionBatches = Array.isArray(po?.batches) ? po.batches : [];
    const selectedId = Number(form.production_batch_id || wo?.production_batch_id || 0);
    if (selectedId) {
      const selected = productionBatches.find((b: any) => Number(b?.id || 0) === selectedId);
      if (selected) return selected;
    }
    return productionBatches.length === 1 ? productionBatches[0] : null;
  }, [form.production_batch_id, po?.batches, wo?.production_batch_id]);
  const createdBundlesBatchLabel = createdBundlesBatch
    ? formatBatchLabel(createdBundlesBatch, po?.id)
    : form.production_batch_id
      ? `${t("field.batch")} #${form.production_batch_id}`
      : t("field.batch");

  useEffect(() => {
    if (!Array.isArray(po?.items) || po.items.length === 0) return;
    const hasPrintingStage = Array.isArray(po?.work_orders) && po.work_orders.some((w: any) => w.operation === "printing");
    const nextStage: "sewing" | "printing" = hasPrintingStage ? "printing" : "sewing";
    const defaultBundleQty = 50;
    const targetMap = distributeBundleTargets(po.items, bundleTargetTotal);
    setBundles((prev) => {
      const byKey = new Map(prev.map((row) => [itemKey(row.color, row.size), row]));
      const recalculated = po.items
        .filter((it: any) => Number(it?.planned_quantity || 0) > 0)
        .map((it: any) => {
          const color = String(it?.color || "").trim() || "-";
          const size = String(it?.size || "").trim() || "-";
          const key = itemKey(color, size);
          const existing = byKey.get(key);
          const qtyPerBundle = Math.max(1, Number(existing?.quantity || defaultBundleQty));
          const targetQty = targetMap.get(key) || 0;
          return {
            color,
            size,
            quantity: qtyPerBundle,
            count: Math.max(1, Math.ceil(targetQty / qtyPerBundle)),
            next: existing?.next || nextStage,
          };
        });
      return recalculated.length > 0 ? recalculated : prev;
    });
    if (!bundlesAutofilled) {
      setBundlesAutofilled(true);
    }
  }, [po?.items, po?.work_orders, bundleTargetTotal, bundlesAutofilled]);

  useEffect(() => {
    if (!canSplitHere) return;
    const plannedQty = Number(wo?.planned_output_qty || po?.planned_quantity || 0);
    setSplitRows((prev) => (prev.length > 0 ? prev : autoSplitRows(plannedQty, splitMax)));
  }, [canSplitHere, po?.planned_quantity, splitMax, wo?.planned_output_qty]);

  useEffect(() => {
    if (!isAlreadyBatched || !Array.isArray(po?.batches) || po.batches.length === 0) return;
    setForm((prev) => {
      if (prev.production_batch_id) return prev;
      return { ...prev, production_batch_id: Number(po.batches[0].id || 0) };
    });
  }, [isAlreadyBatched, po?.batches]);

  function setB(i: number, p: Partial<BundlePlan>) {
    setBundles(bundles.map((b, j) => (i === j ? { ...b, ...p } : b)));
  }
  function setBQty(i: number, nextQtyRaw: number) {
    const nextQty = Math.max(1, Number(nextQtyRaw || 0));
    setBundles((prev) => prev.map((b, j) => {
      if (i !== j) return b;
      const key = itemKey(b.color, b.size);
      const targetQty = bundleTargetQtyByKey.get(key) ?? (Number(b.quantity || 0) * Number(b.count || 1));
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

  function updateSplitRow(index: number, patch: Partial<SplitRow>) {
    setSplitRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addSplitRow() {
    setSplitRows((prev) => [...prev, { name: `Batch ${prev.length + 1}`, planned_quantity: 0, start_date: "", deadline: "", notes: "" }]);
  }

  function removeSplitRow(index: number) {
    setSplitRows((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)));
  }

  async function splitIntoBatches() {
    if (!canSplitHere) return;
    setSplitErr("");
    const rows = splitRows.map((row) => ({
      ...row,
      name: String(row.name || "").trim(),
      planned_quantity: Number(row.planned_quantity || 0),
    }));
    if (rows.some((row) => !Number.isFinite(row.planned_quantity) || row.planned_quantity <= 0)) {
      setSplitErr(t("batch.quantityGreaterThanZero"));
      return;
    }
    setSplitBusy(true);
    try {
      const payloadRows = rows.map((row) => ({
        name: row.name || null,
        planned_quantity: row.planned_quantity,
        start_date: row.start_date ? new Date(row.start_date).toISOString() : null,
        deadline: row.deadline ? new Date(row.deadline).toISOString() : null,
        notes: row.notes ? row.notes : null,
      }));
      await api.post(`/api/work-orders/${id}/split-batches`, { batches: payloadRows });
      await Promise.all([mutatePo(), mutateWo(), mutateBatchProgress()]);
      setDoneMsg(t("batch.planSaved"));
    } catch (e: any) {
      setSplitErr(e.message || "Failed to split into batches");
    } finally {
      setSplitBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setDoneMsg("");
    if (isAlreadyBatched && !form.production_batch_id) {
      setErr(t("batch.selectBeforeSaving", { operation: operationLabel("cutting", t).toLowerCase() }));
      return;
    }
    setSubmitting(true);
    try {
      const r = await api.post("/api/cutting/records", {
        work_order_id: id,
        ...form,
        passed_pieces: Number(form.cut_pieces || 0),
        defective_pieces: 0,
        production_batch_id: form.production_batch_id || null,
        fabric_batch_id: form.fabric_batch_id || null,
        bundles,
      });
      const created = Array.isArray(r?.bundles) ? r.bundles : [];
      setCreatedBundles(created);
      setCreatedBundlesExpanded(false);
      setDoneMsg(t("msg.cuttingDone", { count: created.length }));
      await mutateBatchProgress();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title={t("page.cutting.title", { id })}
        subtitle={wo ? t("page.cutting.subtitle", { op: operationLabel(wo.operation, t), status: statusLabel(wo.status, t) }) : ""}
      />
      <WorkOrderProductInfo
        t={t}
        so={so}
        po={productInfoPo}
        wo={wo}
        model={model}
        customerName={so?.customer_id ? (customerMap.get(so.customer_id) || `#${so.customer_id}`) : null}
        statusText={wo ? statusLabel(wo.status, t) : "-"}
      />

      {isAlreadyBatched && (
        <div className="card mb-4 p-4">
          <div className="mb-2 text-base font-semibold">{t("batch.managedInsideWorkOrder")}</div>
          <div className="mb-3 text-sm text-slate-600">
            {t("batch.recordAction", { operation: operationLabel("cutting", t).toLowerCase() })}
          </div>
          <div className="overflow-x-auto">
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>{t("field.batch")}</th>
                  <th>{t("statusValue.planned")}</th>
                  <th>{t("field.remaining")}</th>
                  <th>{t("page.processes.progress")}</th>
                </tr>
              </thead>
              <tbody>
                {batchItems.map((row: any) => (
                  <tr key={row.id}>
                    <td>
                      <div className="font-medium">{formatBatchLabel(row, po?.id)}</div>
                      <div className="text-xs text-slate-500">{formatBatchSerial(row, po?.id)}</div>
                    </td>
                    <td>{row.planned_quantity}</td>
                    <td>{row.remaining_quantity}</td>
                    <td>{row.progress_pct}%</td>
                  </tr>
                ))}
                {batchItems.length === 0 && (
                  <tr>
                    <td colSpan={4} className="text-slate-500">{t("batch.noProgressYet")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {canSplitHere && (
        <div className="card mb-4 p-4">
          <div className="mb-2 text-base font-semibold">{t("batch.defineInsideWorkOrder")}</div>
          <div className="mb-3 text-sm text-slate-600">
            {t("batch.defineHint")}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-[220px_auto] gap-3 items-end mb-3">
            <div>
              <label className="label">{t("batch.maxPiecesPerBatch")}</label>
              <input
                className="input"
                type="number"
                min={1}
                value={splitMax}
                onChange={(e) => setSplitMax(Math.max(1, Number(e.target.value) || 1))}
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn"
                onClick={() => setSplitRows(autoSplitRows(Number(wo?.planned_output_qty || po?.planned_quantity || 0), splitMax))}
                disabled={splitBusy}
              >
                {t("batch.autoSplit")}
              </button>
              <button type="button" className="btn" onClick={addSplitRow} disabled={splitBusy}>{t("batch.addBatch")}</button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>{t("field.batch")}</th>
                  <th>{t("batch.quantity")}</th>
                  <th>{t("batch.startDate")}</th>
                  <th>{t("field.deadline")}</th>
                  <th>{t("field.notes")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {splitRows.map((row, index) => (
                  <tr key={index}>
                    <td>
                      <input className="input min-w-32" value={row.name} onChange={(e) => updateSplitRow(index, { name: e.target.value })} />
                    </td>
                    <td>
                      <input
                        className="input w-28"
                        type="number"
                        min={1}
                        value={row.planned_quantity}
                        onChange={(e) => updateSplitRow(index, { planned_quantity: Number(e.target.value) || 0 })}
                      />
                    </td>
                    <td>
                      <input className="input" type="date" value={row.start_date} onChange={(e) => updateSplitRow(index, { start_date: e.target.value })} />
                    </td>
                    <td>
                      <input className="input" type="date" value={row.deadline} onChange={(e) => updateSplitRow(index, { deadline: e.target.value })} />
                    </td>
                    <td>
                      <input className="input min-w-44" value={row.notes} onChange={(e) => updateSplitRow(index, { notes: e.target.value })} />
                    </td>
                    <td>
                      <button type="button" className="btn btn-danger" onClick={() => removeSplitRow(index)} disabled={splitRows.length <= 1 || splitBusy}>
                        {t("btn.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-sm">
            {t("batch.totalInBatches")} <span className="font-semibold">{splitTotal}</span> / {Number(wo?.planned_output_qty || po?.planned_quantity || 0)}
          </div>
          {splitErr && <div className="mt-2 text-sm text-red-600">{splitErr}</div>}
          <div className="mt-3">
            <button type="button" className="btn btn-primary" onClick={splitIntoBatches} disabled={splitBusy}>
              {splitBusy ? t("common.saving") : t("batch.saveBatchPlan")}
            </button>
          </div>
        </div>
      )}

      <form onSubmit={submit} className="card space-y-5 p-6">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          {isAlreadyBatched && (
            <div>
              <label className="label">{t("batch.orderBatch")}</label>
              <select
                className="input"
                value={form.production_batch_id}
                onChange={(e) => setForm({ ...form, production_batch_id: Number(e.target.value) })}
              >
                <option value={0}>{t("batch.selectBatch")}</option>
                {(po?.batches || []).map((b: any) => (
                  <option key={b.id} value={b.id}>
                    {formatBatchLabel(b, po?.id)} ({b.planned_quantity})
                  </option>
                ))}
              </select>
            </div>
          )}
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
          <div className="overflow-hidden rounded-lg border border-[#e3dfd3] bg-[#fdfcf8]">
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-[#f7f4ec]"
              aria-expanded={createdBundlesExpanded}
              onClick={() => setCreatedBundlesExpanded((open) => !open)}
            >
              <div className="flex min-w-0 items-center gap-3">
                {createdBundlesExpanded ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                <div className="min-w-0">
                  <div className="label !mb-0">{t("field.batchNo")}</div>
                  <div className="truncate font-medium">{createdBundlesBatchLabel}</div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="badge">{createdBundles.length} {t("nav.bundles").toLowerCase()}</span>
                <span className="text-xs font-medium text-[#56503f]">
                  {createdBundlesExpanded ? t("btn.hideLabels") : t("btn.showLabels")}
                </span>
              </div>
            </button>
            {createdBundlesExpanded && (
              <div className="overflow-x-auto border-t border-[#ecebe3]">
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
        </div>
      )}
    </div>
  );
}
