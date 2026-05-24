"use client";
import { useState } from "react";
import useSWR from "swr";
import { Plus, Trash2 } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

type EstimateFormState = {
  orderId: number;
  orderNo: string;
  materialCost: string;
  accessoryCost: string;
  laborPercent: string;
  electricityPercent: string;
  otherPercent: string;
  deadline: string;
  comment: string;
  materials: EstimateMaterialRow[];
};

type EstimateMaterialRow = {
  item_id: number;
  sku: string;
  name: string;
  category?: string | null;
  required_quantity: number;
  available_quantity: number;
  shortage: number;
  unit: string;
  unit_cost: number;
  estimated_cost: number;
};

type BrandedLine = {
  color: string;
  size: string;
  quantity: number;
};

type BatchPlanRow = {
  name: string;
  planned_quantity: number;
  start_date: string;
  deadline: string;
  notes: string;
};

type BatchPlanState = {
  orderId: number;
  orderNo: string;
  totalQty: number;
  maxPerBatch: number;
  rows: BatchPlanRow[];
};

const DEFAULT_LABOR_PERCENT = 12;
const DEFAULT_ELECTRICITY_PERCENT = 4;
const DEFAULT_OTHER_PERCENT = 3;
const SIZE_OPTIONS = ["44", "46", "48", "50", "52", "54", "56", "58", "60", "62", "64"];

function num(v: string | number | null | undefined): number {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

function splitEstimateRows(rows: EstimateMaterialRow[]) {
  const materialRows = rows.filter((m) => {
    const c = String(m.category || "").toLowerCase();
    return c === "fabric" || c === "semi_finished" || c === "";
  });
  const accessoryRows = rows.filter((m) => {
    const c = String(m.category || "").toLowerCase();
    return c === "accessory" || c === "packaging";
  });
  return { materialRows, accessoryRows };
}

function autoSplitBatchRows(totalQty: number, maxPerBatch: number): BatchPlanRow[] {
  const safeTotal = Math.max(0, Number(totalQty || 0));
  const safeMax = Math.max(1, Number(maxPerBatch || 1));
  if (safeTotal <= 0) {
    return [{ name: "Batch 1", planned_quantity: 0, start_date: "", deadline: "", notes: "" }];
  }
  const out: BatchPlanRow[] = [];
  let left = safeTotal;
  let idx = 1;
  while (left > 0) {
    const qty = Math.min(safeMax, left);
    out.push({
      name: `Batch ${idx}`,
      planned_quantity: qty,
      start_date: "",
      deadline: "",
      notes: "",
    });
    left -= qty;
    idx += 1;
  }
  return out;
}

export default function PlanningDashboard() {
  const { t } = useT();
  const { data: dash } = useSWR<any>("/api/dashboard/planning", fetcher);
  const { data: orders, mutate: mutateOrders } = useSWR<any[]>("/api/sales-orders?order_type=client_order&page_size=200", fetcher);
  const { data: models } = useSWR<any[]>("/api/models?status=approved", fetcher);
  const [brandedForm, setBrandedForm] = useState<{ model_id: number; deadline: string; lines: BrandedLine[] }>({
    model_id: 0,
    deadline: "",
    lines: [{ color: "white", size: "46", quantity: 50 }],
  });
  const [brandedSizeFrom, setBrandedSizeFrom] = useState("46");
  const [brandedSizeTo, setBrandedSizeTo] = useState("56");
  const [brandedDistributeQty, setBrandedDistributeQty] = useState(6000);
  const [brandedSaving, setBrandedSaving] = useState(false);
  const [brandedErr, setBrandedErr] = useState("");
  const [busyOrderId, setBusyOrderId] = useState<number | null>(null);
  const [estimateForm, setEstimateForm] = useState<EstimateFormState | null>(null);
  const [batchPlan, setBatchPlan] = useState<BatchPlanState | null>(null);
  const [batchPlanErr, setBatchPlanErr] = useState("");

  const planningOrders = (orders || []).filter((o) => ["confirmed", "pending_sales_approval", "planning_approved"].includes(o.status));
  const brandedTotalQty = brandedForm.lines.reduce((sum, line) => sum + Number(line.quantity || 0), 0);
  const selectedBrandedModel = models?.find((m) => Number(m.id) === Number(brandedForm.model_id)) || null;

  function updateBrandedLine(i: number, patch: Partial<BrandedLine>) {
    setBrandedForm((prev) => ({
      ...prev,
      lines: prev.lines.map((line, idx) => (idx === i ? { ...line, ...patch } : line)),
    }));
  }

  function addBrandedLine() {
    setBrandedForm((prev) => ({
      ...prev,
      lines: [...prev.lines, { color: prev.lines[0]?.color || "white", size: "46", quantity: 1 }],
    }));
  }

  function removeBrandedLine(i: number) {
    setBrandedForm((prev) => {
      if (prev.lines.length <= 1) return prev;
      return { ...prev, lines: prev.lines.filter((_, idx) => idx !== i) };
    });
  }

  function distributeBrandedBySizeRange() {
    setBrandedErr("");
    const startIdx = SIZE_OPTIONS.indexOf(brandedSizeFrom);
    const endIdx = SIZE_OPTIONS.indexOf(brandedSizeTo);
    if (startIdx < 0 || endIdx < 0 || startIdx > endIdx) {
      setBrandedErr(t("newso.invalidSizeRange"));
      return;
    }
    if (!Number.isFinite(brandedDistributeQty) || brandedDistributeQty <= 0) {
      setBrandedErr(t("newso.invalidTotalQty"));
      return;
    }

    const selectedSizes = SIZE_OPTIONS.slice(startIdx, endIdx + 1);
    const count = selectedSizes.length;
    const qtyPerSize = Math.floor(brandedDistributeQty / count);
    let remainder = brandedDistributeQty % count;
    const baseColor = brandedForm.lines[0]?.color || "white";

    const nextLines: BrandedLine[] = selectedSizes.map((size) => {
      const addOne = remainder > 0 ? 1 : 0;
      if (remainder > 0) remainder -= 1;
      return { color: baseColor, size, quantity: qtyPerSize + addOne };
    });

    setBrandedForm((prev) => ({ ...prev, lines: nextLines }));
  }

  async function createPOForSO(soId: number, batches?: BatchPlanRow[]) {
    setBusyOrderId(soId);
    try {
      const so = await api.get(`/api/sales-orders/${soId}`);
      const items = (so.items || []).map((i: any) => ({ model_id: i.model_id, color: i.color, size: i.size, planned_quantity: i.quantity }));
      const normalizedBatches = (batches || [])
        .map((b) => ({
          name: String(b.name || "").trim() || null,
          planned_quantity: Number(b.planned_quantity || 0),
          start_date: b.start_date ? new Date(b.start_date).toISOString() : null,
          deadline: b.deadline ? new Date(b.deadline).toISOString() : null,
          notes: String(b.notes || "").trim() || null,
        }))
        .filter((b) => b.planned_quantity > 0);
      const po = await api.post("/api/planning/create-production-order", {
        production_type: "client_order",
        sales_order_id: soId,
        model_id: so.items?.[0]?.model_id,
        planned_quantity: items.reduce((s: number, i: any) => s + i.planned_quantity, 0),
        // Carry the customer deadline through to the production order so the
        // process tracker shows a meaningful "due by" value.
        deadline: so.deadline ?? null,
        items,
        batches: normalizedBatches,
      });
      // Cascade the deadline into each work-order (cutting/printing/sewing/packaging)
      // unless explicit per-batch planning is used.
      if (so.deadline && normalizedBatches.length === 0) {
        try { await api.post(`/api/production-orders/${po.id}/cascade-deadlines`); } catch {}
      }
      window.location.href = `/production-orders/${po.id}`;
    } finally {
      setBusyOrderId(null);
    }
  }

  async function openBatchPlannerForSO(soId: number) {
    setBusyOrderId(soId);
    setBatchPlanErr("");
    try {
      const so = await api.get(`/api/sales-orders/${soId}`);
      const totalQty = (so.items || []).reduce((sum: number, row: any) => sum + Number(row.quantity || 0), 0);
      const maxPerBatch = 600;
      setBatchPlan({
        orderId: soId,
        orderNo: so.order_no || `#${soId}`,
        totalQty,
        maxPerBatch,
        rows: autoSplitBatchRows(totalQty, maxPerBatch),
      });
    } finally {
      setBusyOrderId(null);
    }
  }

  function updateBatchPlanRow(index: number, patch: Partial<BatchPlanRow>) {
    setBatchPlan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        rows: prev.rows.map((row, i) => (i === index ? { ...row, ...patch } : row)),
      };
    });
  }

  function addBatchPlanRow() {
    setBatchPlan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        rows: [
          ...prev.rows,
          { name: `Batch ${prev.rows.length + 1}`, planned_quantity: 0, start_date: "", deadline: "", notes: "" },
        ],
      };
    });
  }

  function removeBatchPlanRow(index: number) {
    setBatchPlan((prev) => {
      if (!prev || prev.rows.length <= 1) return prev;
      return {
        ...prev,
        rows: prev.rows.filter((_, i) => i !== index),
      };
    });
  }

  async function createPOFromBatchPlan() {
    if (!batchPlan) return;
    const rows = batchPlan.rows.map((row) => ({
      ...row,
      planned_quantity: Number(row.planned_quantity || 0),
      name: String(row.name || "").trim(),
    }));
    if (rows.some((row) => !Number.isFinite(row.planned_quantity) || row.planned_quantity <= 0)) {
      setBatchPlanErr("Each batch quantity must be greater than zero.");
      return;
    }
    const total = rows.reduce((sum, row) => sum + row.planned_quantity, 0);
    if (total !== batchPlan.totalQty) {
      setBatchPlanErr(`Batch total must match order quantity (${batchPlan.totalQty}). Current total: ${total}.`);
      return;
    }
    setBatchPlanErr("");
    await createPOForSO(batchPlan.orderId, rows);
  }

  async function openEstimateDialog(soId: number) {
    setBusyOrderId(soId);
    try {
      const order = planningOrders.find((o) => o.id === soId);
      const estimate = await api.get(`/api/planning/estimate/${soId}`);
      const baseTotalCost = num(estimate.estimated_material_cost);
      const materials = Array.isArray(estimate.materials) ? estimate.materials : [];
      const { materialRows, accessoryRows } = splitEstimateRows(materials);
      const accessoryRowsCost = round2(accessoryRows.reduce((sum, row) => sum + num(row.estimated_cost), 0));
      const baseAccessoryCost = accessoryRows.length > 0 ? accessoryRowsCost : 0;
      const baseMaterialCost = materialRows.length > 0
        ? round2(Math.max(0, baseTotalCost - baseAccessoryCost))
        : baseTotalCost;
      const savedLaborCost = num(estimate.estimated_labor_cost);
      const savedElectricityCost = num(estimate.estimated_electricity_cost);
      const savedOtherCost = num(estimate.estimated_other_expenses);
      const baseCost = baseMaterialCost + baseAccessoryCost;
      const laborPercent = baseCost > 0 ? (savedLaborCost / baseCost) * 100 : DEFAULT_LABOR_PERCENT;
      const electricityPercent = baseCost > 0 ? (savedElectricityCost / baseCost) * 100 : DEFAULT_ELECTRICITY_PERCENT;
      const otherPercent = baseCost > 0 ? (savedOtherCost / baseCost) * 100 : DEFAULT_OTHER_PERCENT;
      setEstimateForm({
        orderId: soId,
        orderNo: order?.order_no || `#${soId}`,
        materialCost: baseMaterialCost.toFixed(2),
        accessoryCost: baseAccessoryCost.toFixed(2),
        laborPercent: round2(laborPercent).toFixed(2),
        electricityPercent: round2(electricityPercent).toFixed(2),
        otherPercent: round2(otherPercent).toFixed(2),
        deadline: order?.deadline ? String(order.deadline).slice(0, 10) : "",
        comment: "",
        materials,
      });
    } finally {
      setBusyOrderId(null);
    }
  }

  async function submitEstimateToSales() {
    if (!estimateForm) return;
    const materialCost = Number(estimateForm.materialCost);
    const accessoryCost = Number(estimateForm.accessoryCost);
    const laborPercent = Number(estimateForm.laborPercent);
    const electricityPercent = Number(estimateForm.electricityPercent);
    const otherPercent = Number(estimateForm.otherPercent);
    if (!Number.isFinite(materialCost) || materialCost < 0) return;
    if (!Number.isFinite(accessoryCost) || accessoryCost < 0) return;
    if (!Number.isFinite(laborPercent) || laborPercent < 0) return;
    if (!Number.isFinite(electricityPercent) || electricityPercent < 0) return;
    if (!Number.isFinite(otherPercent) || otherPercent < 0) return;
    if (!estimateForm.deadline) return;
    const baseCost = materialCost + accessoryCost;
    const laborCost = round2(baseCost * laborPercent / 100);
    const electricityCost = round2(baseCost * electricityPercent / 100);
    const otherExpenses = round2(baseCost * otherPercent / 100);

    setBusyOrderId(estimateForm.orderId);
    try {
      await api.post(`/api/planning/submit-estimate/${estimateForm.orderId}`, {
        estimated_material_cost: baseCost,
        estimated_labor_cost: laborCost,
        estimated_electricity_cost: electricityCost,
        estimated_other_expenses: otherExpenses,
        planned_deadline: estimateForm.deadline,
        estimate_comment: estimateForm.comment.trim() || null,
      });
      setEstimateForm(null);
      await mutateOrders();
    } finally {
      setBusyOrderId(null);
    }
  }

  async function createBranded(e: React.FormEvent) {
    e.preventDefault();
    setBrandedErr("");
    if (!brandedForm.model_id) {
      setBrandedErr(t("newso.selectModel"));
      return;
    }

    const items = brandedForm.lines
      .map((line) => ({
        model_id: brandedForm.model_id,
        color: String(line.color || "").trim() || "white",
        size: String(line.size || "").trim() || "46",
        planned_quantity: Number(line.quantity || 0),
      }))
      .filter((line) => line.planned_quantity > 0);

    if (!items.length) {
      setBrandedErr(t("newso.invalidTotalQty"));
      return;
    }

    const plannedQty = items.reduce((sum, line) => sum + line.planned_quantity, 0);
    setBrandedSaving(true);
    try {
      const po = await api.post("/api/planning/create-branded-production", {
        production_type: "branded_stock",
        model_id: brandedForm.model_id,
        planned_quantity: plannedQty,
        deadline: brandedForm.deadline || null,
        items,
      });
      if (brandedForm.deadline) {
        try { await api.post(`/api/production-orders/${po.id}/cascade-deadlines`); } catch {}
      }
      window.location.href = `/production-orders/${po.id}`;
    } catch (e: any) {
      setBrandedErr(e?.message || t("page.warehouseMap.actionFailed"));
    } finally {
      setBrandedSaving(false);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.planning.title")} subtitle={t("page.planning.subtitle")} />
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.planning.ordersWaiting")}</div><div className="text-2xl font-semibold">{dash?.orders_waiting_planning ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.planning.activeProduction")}</div><div className="text-2xl font-semibold">{dash?.active_production_orders ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.planning.brandedPlans")}</div><div className="text-2xl font-semibold">{dash?.branded_plans ?? 0}</div></div>
      </div>

      <div className="card p-4 mb-6">
        <h2 className="font-medium mb-3">{t("page.planning.confirmedAwaiting")}</h2>
        <table className="table">
          <thead><tr><th>{t("field.orderNo")}</th><th>{t("field.customer")}</th><th>{t("field.total")}</th><th>{t("common.status")}</th><th></th></tr></thead>
          <tbody>
            {planningOrders.map((o) => (
              <tr key={o.id}>
                <td>{o.order_no}</td>
                <td>{o.customer?.name || o.customer_name || o.customer_id || "-"}</td>
                <td>${Number(o.total_amount).toFixed(2)}</td>
                <td>{statusLabel(o.status, t)}</td>
                <td>
                  {o.status === "confirmed" && (
                    <button className="btn" disabled={busyOrderId === o.id} onClick={() => openEstimateDialog(o.id)}>
                      {busyOrderId === o.id ? t("common.loading") : t("btn.sendEstimateToSales")}
                    </button>
                  )}
                  {o.status === "pending_sales_approval" && (
                    <button className="btn" disabled>
                      {t("page.planning.waitingSalesApproval")}
                    </button>
                  )}
                  {o.status === "planning_approved" && (
                    <button className="btn btn-primary" disabled={busyOrderId === o.id} onClick={() => createPOForSO(o.id)}>
                      {busyOrderId === o.id ? t("common.creating") : t("btn.createProductionOrder")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {batchPlan && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <div className="card w-full max-w-5xl mx-auto p-5 space-y-4">
              <div className="text-lg font-semibold">Batch Planning for {batchPlan.orderNo}</div>
              <div className="text-sm text-slate-600">
                Split this order into production batches. Cutting capacity is usually limited per batch, so you can plan today/tomorrow work separately.
              </div>
              <div className="grid grid-cols-1 md:grid-cols-[220px_auto] gap-3 items-end">
                <div>
                  <label className="label">Max pieces per batch</label>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    value={batchPlan.maxPerBatch}
                    onChange={(e) => setBatchPlan((prev) => prev ? { ...prev, maxPerBatch: Math.max(1, Number(e.target.value) || 1) } : prev)}
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setBatchPlan((prev) => prev ? { ...prev, rows: autoSplitBatchRows(prev.totalQty, prev.maxPerBatch) } : prev)}
                  >
                    Auto split
                  </button>
                  <button type="button" className="btn" onClick={addBatchPlanRow}>Add batch</button>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="table text-sm">
                  <thead>
                    <tr>
                      <th>Batch</th>
                      <th>Quantity</th>
                      <th>Start date</th>
                      <th>Deadline</th>
                      <th>Notes</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {batchPlan.rows.map((row, index) => (
                      <tr key={index}>
                        <td>
                          <input
                            className="input min-w-32"
                            value={row.name}
                            onChange={(e) => updateBatchPlanRow(index, { name: e.target.value })}
                          />
                        </td>
                        <td>
                          <input
                            className="input w-28"
                            type="number"
                            min={1}
                            value={row.planned_quantity}
                            onChange={(e) => updateBatchPlanRow(index, { planned_quantity: Number(e.target.value) || 0 })}
                          />
                        </td>
                        <td>
                          <input
                            className="input"
                            type="date"
                            value={row.start_date}
                            onChange={(e) => updateBatchPlanRow(index, { start_date: e.target.value })}
                          />
                        </td>
                        <td>
                          <input
                            className="input"
                            type="date"
                            value={row.deadline}
                            onChange={(e) => updateBatchPlanRow(index, { deadline: e.target.value })}
                          />
                        </td>
                        <td>
                          <input
                            className="input min-w-44"
                            value={row.notes}
                            onChange={(e) => updateBatchPlanRow(index, { notes: e.target.value })}
                          />
                        </td>
                        <td>
                          <button type="button" className="btn btn-danger" onClick={() => removeBatchPlanRow(index)} disabled={batchPlan.rows.length <= 1}>
                            {t("btn.remove")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="text-sm">
                Total in batches: <span className="font-semibold">{batchPlan.rows.reduce((sum, row) => sum + Number(row.planned_quantity || 0), 0)}</span> / {batchPlan.totalQty}
              </div>
              {batchPlanErr && <div className="text-sm text-red-600">{batchPlanErr}</div>}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setBatchPlan(null);
                    setBatchPlanErr("");
                  }}
                  disabled={busyOrderId === batchPlan.orderId}
                >
                  {t("btn.cancel")}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={createPOFromBatchPlan}
                  disabled={busyOrderId === batchPlan.orderId}
                >
                  {busyOrderId === batchPlan.orderId ? t("common.creating") : "Create production with batches"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {estimateForm && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <div className="card w-full max-w-4xl mx-auto p-5 space-y-4">
            <div className="text-lg font-semibold">{t("page.planning.estimateFor", { orderNo: estimateForm.orderNo })}</div>
            {(() => {
              const materialCost = num(estimateForm.materialCost);
              const accessoryCost = num(estimateForm.accessoryCost);
              const baseCost = materialCost + accessoryCost;
              const laborPercent = num(estimateForm.laborPercent);
              const electricityPercent = num(estimateForm.electricityPercent);
              const otherPercent = num(estimateForm.otherPercent);
              const laborCost = round2(baseCost * laborPercent / 100);
              const electricityCost = round2(baseCost * electricityPercent / 100);
              const otherExpenses = round2(baseCost * otherPercent / 100);
              const netPrice = baseCost + laborCost + electricityCost + otherExpenses;
              const price15 = netPrice * 1.15;
              const price20 = netPrice * 1.20;
              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="label">{t("field.estimatedMaterialCost")}</label>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        step="0.01"
                        value={estimateForm.materialCost}
                        onChange={(e) => setEstimateForm({ ...estimateForm, materialCost: e.target.value })}
                      />
                    </div>
                    <div>
                      <label className="label">{t("field.accessoryCost")}</label>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        step="0.01"
                        value={estimateForm.accessoryCost}
                        onChange={(e) => setEstimateForm({ ...estimateForm, accessoryCost: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="text-xs text-slate-500">
                      {t("page.planning.overheadHint")}
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="card p-3">
                      <div className="text-xs text-slate-500 uppercase tracking-wide">{t("page.planning.netPrice")}</div>
                      <div className="text-lg font-semibold">${netPrice.toFixed(2)}</div>
                    </div>
                    <div className="card p-3">
                      <div className="text-xs text-slate-500 uppercase tracking-wide">{t("page.planning.priceWithProfit15")}</div>
                      <div className="text-lg font-semibold">${price15.toFixed(2)}</div>
                    </div>
                    <div className="card p-3">
                      <div className="text-xs text-slate-500 uppercase tracking-wide">{t("page.planning.priceWithProfit20")}</div>
                      <div className="text-lg font-semibold">${price20.toFixed(2)}</div>
                    </div>
                  </div>
                </div>
              );
            })()}
            {(() => {
              const allRows = estimateForm.materials || [];
              const { materialRows, accessoryRows } = splitEstimateRows(allRows);
              const materialCost = num(estimateForm.materialCost);
              const accessoryCost = num(estimateForm.accessoryCost);
              const baseCost = materialCost + accessoryCost;
              const laborPercent = num(estimateForm.laborPercent);
              const electricityPercent = num(estimateForm.electricityPercent);
              const otherPercent = num(estimateForm.otherPercent);
              const laborCost = round2(baseCost * laborPercent / 100);
              const electricityCost = round2(baseCost * electricityPercent / 100);
              const otherCost = round2(baseCost * otherPercent / 100);
              const renderEstimateRows = (rows: EstimateMaterialRow[]) => (
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("field.item")}</th>
                        <th>{t("field.usage")}</th>
                        <th>{t("field.unitCost")}</th>
                        <th>{t("field.totalCost")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.item_id}>
                          <td>
                            <div className="font-medium">{row.name}</div>
                            <div className="text-xs text-slate-500">{row.sku}</div>
                          </td>
                          <td>{Number(row.required_quantity || 0).toFixed(2)} {row.unit}</td>
                          <td>${Number(row.unit_cost || 0).toFixed(2)}</td>
                          <td>${Number(row.estimated_cost || 0).toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );

              return (
                <div className="space-y-4">
                  <div>
                    <div className="text-sm font-semibold mb-2">{t("page.planning.materialUsageCost")}</div>
                    {materialRows.length > 0 ? renderEstimateRows(materialRows) : <div className="text-sm text-slate-500">{t("page.planning.noMaterialRows")}</div>}
                  </div>
                  <div>
                    <div className="text-sm font-semibold mb-2">{t("page.planning.accessoryUsageCost")}</div>
                    {accessoryRows.length > 0 ? renderEstimateRows(accessoryRows) : <div className="text-sm text-slate-500">{t("page.planning.noAccessoryRows")}</div>}
                  </div>
                  <div>
                    <div className="text-sm font-semibold mb-2">{t("page.planning.otherExpensesApprox")}</div>
                    <div className="overflow-x-auto">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>{t("field.expense")}</th>
                            <th>{t("field.approxPercent")}</th>
                            <th>{t("field.baseCost")}</th>
                            <th>{t("field.approxCost")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td>{t("expense.labor")}</td>
                            <td>
                              <input
                                className="input"
                                type="number"
                                min={0}
                                step="0.1"
                                value={estimateForm.laborPercent}
                                onChange={(e) => setEstimateForm({ ...estimateForm, laborPercent: e.target.value })}
                              />
                            </td>
                            <td>${baseCost.toFixed(2)}</td>
                            <td>${laborCost.toFixed(2)}</td>
                          </tr>
                          <tr>
                            <td>{t("expense.electricity")}</td>
                            <td>
                              <input
                                className="input"
                                type="number"
                                min={0}
                                step="0.1"
                                value={estimateForm.electricityPercent}
                                onChange={(e) => setEstimateForm({ ...estimateForm, electricityPercent: e.target.value })}
                              />
                            </td>
                            <td>${baseCost.toFixed(2)}</td>
                            <td>${electricityCost.toFixed(2)}</td>
                          </tr>
                          <tr>
                            <td>{t("expense.other")}</td>
                            <td>
                              <input
                                className="input"
                                type="number"
                                min={0}
                                step="0.1"
                                value={estimateForm.otherPercent}
                                onChange={(e) => setEstimateForm({ ...estimateForm, otherPercent: e.target.value })}
                              />
                            </td>
                            <td>${baseCost.toFixed(2)}</td>
                            <td>${otherCost.toFixed(2)}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              );
            })()}
            <div>
              <label className="label">{t("field.planningDeadline")}</label>
              <input
                className="input"
                type="date"
                value={estimateForm.deadline}
                onChange={(e) => setEstimateForm({ ...estimateForm, deadline: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="label">{t("field.planningComment")}</label>
              <textarea
                className="input min-h-24"
                placeholder={t("ph.salesApprovalComment")}
                value={estimateForm.comment}
                onChange={(e) => setEstimateForm({ ...estimateForm, comment: e.target.value })}
              />
            </div>
            <div className="flex justify-end gap-2">
              <button className="btn" onClick={() => setEstimateForm(null)} disabled={busyOrderId === estimateForm.orderId}>{t("btn.cancel")}</button>
              <button className="btn btn-primary" onClick={submitEstimateToSales} disabled={busyOrderId === estimateForm.orderId || !estimateForm.deadline}>
                {busyOrderId === estimateForm.orderId ? t("btn.sending") : t("btn.sendToSales")}
              </button>
            </div>
          </div>
        </div>
        </div>
      )}

      <form onSubmit={createBranded} className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="card">
          <div className="flex items-center justify-between border-b border-[#ecebe3] px-5 py-4">
            <div>
              <h2 className="app-card-title">{t("page.planning.brandedSection")}</h2>
              <p className="mt-1 text-sm text-[#8a8472]">{t("newso.orderDetailsSub")}</p>
            </div>
            <span className="badge bg-[#fbe9dd] text-[#c2410c]">{t("newso.draft")}</span>
          </div>
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="label">{t("field.model")}</label>
                <select
                  className="input"
                  value={brandedForm.model_id}
                  onChange={(e) => setBrandedForm((prev) => ({ ...prev, model_id: Number(e.target.value) }))}
                  required
                >
                  <option value={0}>{t("ph.approvedModel")}</option>
                  {models?.map((m) => (
                    <option key={m.id} value={m.id}>{m.code} - {m.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">{t("field.deadline")}</label>
                <input
                  className="input"
                  type="date"
                  value={brandedForm.deadline}
                  onChange={(e) => setBrandedForm((prev) => ({ ...prev, deadline: e.target.value }))}
                />
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between border-b border-[#ecebe3] px-5 py-4">
            <div>
              <h2 className="app-card-title">{t("newso.lines")}</h2>
              <p className="mt-1 text-sm text-[#8a8472]">
                {t("newso.linesSummary", { lines: brandedForm.lines.length, qty: brandedTotalQty.toLocaleString() })}
              </p>
            </div>
            <button type="button" className="btn" onClick={addBrandedLine}><Plus />{t("newso.addLine")}</button>
          </div>
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <div className="mb-2 text-sm font-semibold text-[#14110b]">{t("newso.sizeHelper")}</div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-[140px_140px_180px_auto] md:items-end">
              <div>
                <label className="label">{t("newso.sizeFrom")}</label>
                <select className="input" value={brandedSizeFrom} onChange={(e) => setBrandedSizeFrom(e.target.value)}>
                  {SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="label">{t("newso.sizeTo")}</label>
                <select className="input" value={brandedSizeTo} onChange={(e) => setBrandedSizeTo(e.target.value)}>
                  {SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="label">{t("newso.sizeTotalQty")}</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={brandedDistributeQty}
                  onChange={(e) => setBrandedDistributeQty(Number(e.target.value) || 0)}
                />
              </div>
              <div className="flex items-end md:pb-[1px]">
                <button type="button" className="btn btn-primary" onClick={distributeBrandedBySizeRange}>
                  {t("newso.distributeEvenly")}
                </button>
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.color")}</th>
                  <th>{t("field.size")}</th>
                  <th>{t("field.qty")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {brandedForm.lines.map((line, i) => (
                  <tr key={i}>
                    <td><input className="input min-w-28" value={line.color} onChange={(e) => updateBrandedLine(i, { color: e.target.value })} /></td>
                    <td>
                      <select className="input min-w-24" value={line.size} onChange={(e) => updateBrandedLine(i, { size: e.target.value })}>
                        {SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </td>
                    <td>
                      <input
                        className="input w-28"
                        type="number"
                        min={1}
                        value={line.quantity}
                        onChange={(e) => updateBrandedLine(i, { quantity: Number(e.target.value) || 0 })}
                      />
                    </td>
                    <td>
                      <button type="button" className="icon-btn text-red-600" onClick={() => removeBrandedLine(i)} title={t("newso.remove")}>
                        <Trash2 />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="card self-start">
          <div className="border-b border-[#ecebe3] px-5 py-4">
            <h2 className="app-card-title">{t("newso.orderSummary")}</h2>
            <p className="mt-1 text-sm text-[#8a8472]">{t("newso.orderSummarySub")}</p>
          </div>
          <div className="space-y-5 p-5">
            <div className="rounded-lg bg-[#f1efe8] p-4">
              <div className="label">{t("newso.totalQuantity")}</div>
              <div className="mt-1 text-3xl font-semibold">{brandedTotalQty.toLocaleString()}</div>
              <div className="mt-1 text-sm text-[#8a8472]">
                {t("newso.piecesAcross", { qty: brandedTotalQty.toLocaleString(), lines: brandedForm.lines.length })}
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("field.model")}</span>
                <span className="text-right">{selectedBrandedModel ? `${selectedBrandedModel.code} - ${selectedBrandedModel.name}` : "-"}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("field.deadline")}</span>
                <span>{brandedForm.deadline || "-"}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#8a8472]">{t("newso.lines")}</span>
                <span>{brandedForm.lines.length}</span>
              </div>
            </div>
            {brandedErr && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{brandedErr}</div>}
            <button className="btn btn-primary w-full" disabled={brandedSaving}>
              {brandedSaving ? t("newso.creating") : t("btn.createBrandedPlan")}
            </button>
          </div>
        </aside>
      </form>
    </div>
  );
}
