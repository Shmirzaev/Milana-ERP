"use client";
import { useId, useMemo, useState } from "react";
import useSWR from "swr";
import { Check, ChevronDown, Plus, Search, Trash2 } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

type MaterialItem = {
  id: number;
  sku: string;
  name: string;
  unit?: string;
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

type MaterialEstimateDraft = {
  materialCode: string;
  materialAmount: number | "";
  materialUnit: string;
};

type MaterialEstimatePayload = {
  estimated_material_code: string;
  estimated_material_amount: number;
  estimated_material_unit: string;
};

type MaterialEstimateState = MaterialEstimateDraft & {
  orderId: number;
  orderNo: string;
};

type BatchPlanState = {
  orderId: number;
  orderNo: string;
  totalQty: number;
  maxPerBatch: number;
  rows: BatchPlanRow[];
} & MaterialEstimateDraft;

const SIZE_OPTIONS = ["44", "46", "48", "50", "52", "54", "56", "58", "60", "62", "64"];
const DEFAULT_MATERIAL_UNIT = "kg";
const MATERIAL_ESTIMATE_LABEL_CLASS = "label md:min-h-[32px]";

function materialItemSearchText(item: MaterialItem): string {
  return `${item.sku} ${item.name} ${item.unit || ""}`.toLowerCase();
}

function MaterialCodeCombobox({
  value,
  items,
  onChange,
  placeholder,
}: {
  value: string;
  items?: MaterialItem[];
  onChange: (value: string, item?: MaterialItem) => void;
  placeholder?: string;
}) {
  const { t } = useT();
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const search = value.trim().toLowerCase();
  const exactSku = search;
  const filteredItems = useMemo(() => {
    const source = items || [];
    const matches = search
      ? source.filter((item) => materialItemSearchText(item).includes(search))
      : source;
    return matches.slice(0, 10);
  }, [items, search]);

  return (
    <div
      className="relative"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
      <input
        className="input !pl-9 !pr-10"
        value={value}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
        }}
        placeholder={placeholder}
        role="combobox"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-autocomplete="list"
      />
      <button
        type="button"
        className="absolute right-1 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-[#8a8472] transition hover:bg-[#f1efe8] hover:text-[#14110b]"
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => setOpen((prev) => !prev)}
        title={t("common.search")}
        aria-label={t("common.search")}
      >
        <ChevronDown className={`h-4 w-4 transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div id={listboxId} className="absolute left-0 right-0 z-50 mt-1 max-h-60 overflow-auto rounded-md border border-[#ded9ca] bg-[#fdfcf8] py-1 shadow-lg" role="listbox">
          {!items ? (
            <div className="px-3 py-2 text-sm text-[#8a8472]">{t("common.loading")}</div>
          ) : filteredItems.length === 0 ? (
            <div className="px-3 py-2 text-sm text-[#8a8472]">{t("page.search.noMatches")}</div>
          ) : (
            filteredItems.map((item) => {
              const selected = item.sku.toLowerCase() === exactSku;
              return (
                <button
                  key={item.id}
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition hover:bg-[#fdf3eb]"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onChange(item.sku, item);
                    setOpen(false);
                  }}
                  role="option"
                  aria-selected={selected}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-[#14110b]">{item.sku}</span>
                    <span className="block truncate text-xs text-[#6f684f]">
                      {item.name}{item.unit ? ` - ${item.unit}` : ""}
                    </span>
                  </span>
                  {selected && <Check className="h-4 w-4 shrink-0 text-[#c2410c]" />}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

function emptyMaterialEstimate(): MaterialEstimateDraft {
  return { materialCode: "", materialAmount: "", materialUnit: DEFAULT_MATERIAL_UNIT };
}

function validateMaterialEstimate(draft: MaterialEstimateDraft): { payload?: MaterialEstimatePayload; error?: string } {
  const code = String(draft.materialCode || "").trim();
  const unit = String(draft.materialUnit || "").trim() || DEFAULT_MATERIAL_UNIT;
  const amount = Number(draft.materialAmount);
  if (!code) return { error: "Enter material code for the cutting team." };
  if (!Number.isFinite(amount) || amount <= 0) return { error: "Enter estimated material amount greater than zero." };
  return {
    payload: {
      estimated_material_code: code,
      estimated_material_amount: amount,
      estimated_material_unit: unit,
    },
  };
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
  const { data: orders } = useSWR<any[]>("/api/sales-orders?order_type=client_order&page_size=200", fetcher);
  const { data: models } = useSWR<any[]>("/api/models?status=approved", fetcher);
  const { data: materialItems } = useSWR<MaterialItem[]>("/api/inventory/items?group=materials", fetcher);
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
  const [materialEstimate, setMaterialEstimate] = useState<MaterialEstimateState | null>(null);
  const [materialEstimateErr, setMaterialEstimateErr] = useState("");
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

  async function createPOForSO(soId: number, batches?: BatchPlanRow[], material?: MaterialEstimatePayload) {
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
        ...(material || {}),
      }, 60_000);
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

  function openMaterialEstimateForSO(order: any) {
    setMaterialEstimate({
      orderId: Number(order.id),
      orderNo: order.order_no || `#${order.id}`,
      ...emptyMaterialEstimate(),
    });
    setMaterialEstimateErr("");
  }

  async function createPOFromMaterialEstimate() {
    if (!materialEstimate) return;
    const check = validateMaterialEstimate(materialEstimate);
    if (check.error || !check.payload) {
      setMaterialEstimateErr(check.error || "Enter material estimate before creating the production order.");
      return;
    }
    setMaterialEstimateErr("");
    try {
      await createPOForSO(materialEstimate.orderId, undefined, check.payload);
    } catch (e: any) {
      setMaterialEstimateErr(e?.message || "Failed to create production order.");
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
        ...emptyMaterialEstimate(),
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
      setBatchPlanErr(t("batch.quantityGreaterThanZero"));
      return;
    }
    const estimate = validateMaterialEstimate(batchPlan);
    if (estimate.error || !estimate.payload) {
      setBatchPlanErr(estimate.error || "Enter material estimate before creating the production order.");
      return;
    }
    setBatchPlanErr("");
    try {
      await createPOForSO(batchPlan.orderId, rows, estimate.payload);
    } catch (e: any) {
      setBatchPlanErr(e?.message || "Failed to create production order.");
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
      }, 60_000);
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
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4">
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
                  <div className="flex flex-wrap gap-2">
                    <button className="btn btn-primary" disabled={busyOrderId === o.id} onClick={() => openMaterialEstimateForSO(o)}>
                      {busyOrderId === o.id ? t("common.creating") : t("btn.createProductionOrder")}
                    </button>
                    <button className="btn" disabled={busyOrderId === o.id} onClick={() => openBatchPlannerForSO(o.id)}>
                      {t("batch.planBatches")}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {batchPlan && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <div className="card !overflow-visible w-full max-w-5xl mx-auto p-5 space-y-4">
              <div className="text-lg font-semibold">{t("batch.planningFor", { orderNo: batchPlan.orderNo })}</div>
              <div className="text-sm text-slate-600">
                {t("batch.splitOrderHint")}
              </div>
              <div className="rounded-md border border-[#ecebe3] bg-[#fbfaf6] p-4">
                <div className="mb-3">
                  <div className="text-sm font-semibold text-[#14110b]">{t("page.planning.materialEstimateTitle")}</div>
                  <div className="mt-1 text-sm text-slate-600">{t("page.planning.materialEstimateHelp")}</div>
                </div>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_180px_120px]">
                  <div>
                    <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateCode")}</label>
                    <MaterialCodeCombobox
                      value={batchPlan.materialCode}
                      items={materialItems}
                      onChange={(materialCode, item) => setBatchPlan((prev) => prev ? {
                        ...prev,
                        materialCode,
                        materialUnit: item?.unit || prev.materialUnit,
                      } : prev)}
                      placeholder="FAB-COT-001"
                    />
                  </div>
                  <div>
                    <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateAmount")}</label>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step="0.01"
                      value={batchPlan.materialAmount}
                      onChange={(e) => setBatchPlan((prev) => prev ? { ...prev, materialAmount: e.target.value === "" ? "" : Number(e.target.value) } : prev)}
                    />
                  </div>
                  <div>
                    <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateUnit")}</label>
                    <input
                      className="input"
                      value={batchPlan.materialUnit}
                      onChange={(e) => setBatchPlan((prev) => prev ? { ...prev, materialUnit: e.target.value } : prev)}
                    />
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-[220px_auto] gap-3 items-end">
                <div>
                  <label className="label">{t("batch.maxPiecesPerBatch")}</label>
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
                    {t("batch.autoSplit")}
                  </button>
                  <button type="button" className="btn" onClick={addBatchPlanRow}>{t("batch.addBatch")}</button>
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
                {t("batch.totalInBatches")} <span className="font-semibold">{batchPlan.rows.reduce((sum, row) => sum + Number(row.planned_quantity || 0), 0)}</span> / {batchPlan.totalQty}
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
                  {busyOrderId === batchPlan.orderId ? t("common.creating") : t("batch.createProductionWithBatches")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {materialEstimate && (
        <div className="fixed inset-0 z-40 bg-black/40">
          <div className="absolute inset-0 overflow-y-auto p-4 md:p-6">
            <div className="card !overflow-visible w-full max-w-2xl mx-auto p-5 space-y-4">
              <div>
                <div className="text-lg font-semibold">
                  {t("page.planning.materialEstimateTitle")} - {materialEstimate.orderNo}
                </div>
                <div className="mt-1 text-sm text-slate-600">{t("page.planning.materialEstimateHelp")}</div>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_180px_120px]">
                <div>
                  <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateCode")}</label>
                  <MaterialCodeCombobox
                    value={materialEstimate.materialCode}
                    items={materialItems}
                    onChange={(materialCode, item) => setMaterialEstimate((prev) => prev ? {
                      ...prev,
                      materialCode,
                      materialUnit: item?.unit || prev.materialUnit,
                    } : prev)}
                    placeholder="FAB-COT-001"
                  />
                </div>
                <div>
                  <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateAmount")}</label>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step="0.01"
                    value={materialEstimate.materialAmount}
                    onChange={(e) => setMaterialEstimate((prev) => prev ? { ...prev, materialAmount: e.target.value === "" ? "" : Number(e.target.value) } : prev)}
                  />
                </div>
                <div>
                  <label className={MATERIAL_ESTIMATE_LABEL_CLASS}>{t("page.planning.materialEstimateUnit")}</label>
                  <input
                    className="input"
                    value={materialEstimate.materialUnit}
                    onChange={(e) => setMaterialEstimate((prev) => prev ? { ...prev, materialUnit: e.target.value } : prev)}
                  />
                </div>
              </div>
              {materialEstimateErr && <div className="text-sm text-red-600">{materialEstimateErr}</div>}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setMaterialEstimate(null);
                    setMaterialEstimateErr("");
                  }}
                  disabled={busyOrderId === materialEstimate.orderId}
                >
                  {t("btn.cancel")}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={createPOFromMaterialEstimate}
                  disabled={busyOrderId === materialEstimate.orderId}
                >
                  {busyOrderId === materialEstimate.orderId ? t("common.creating") : t("btn.createProductionOrder")}
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
