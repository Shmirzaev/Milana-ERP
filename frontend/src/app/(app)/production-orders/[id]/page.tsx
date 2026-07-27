"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { PackageCheck, RotateCcw } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel } from "@/lib/batchSerial";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { operationLabel, productionTypeLabel, statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { useMe, can } from "@/lib/auth";
import { orderReference } from "@/lib/orderRef";
import { useDialogs } from "@/components/DialogProvider";
import { formatComposition, type MaterialComposition } from "@/lib/materialComposition";
import { formatModelComposition } from "@/lib/modelComposition";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";

type WO = {
  id: number;
  production_batch_id?: number | null;
  operation: string;
  department_id: number;
  status: string;
  planned_input_qty: number;
  actual_input_qty: number;
  actual_output_qty: number;
  passed_qty: number;
  failed_qty: number;
  deadline: string | null;
  assigned_to: number | null;
  sewing_flow_id: number | null;
  is_blocked: boolean;
  block_reason: string | null;
};

type BatchMeta = {
  id: number;
  batch_no: string;
  batch_index: number;
  name: string | null;
  planned_quantity: number;
};

type Assignment = {
  id: number;
  work_order_id: number;
  sewing_flow_id: number;
  quantity: number;
  completed_qty: number;
  planned_start: string | null;
  planned_end: string | null;
  status: string;
  notes: string | null;
};

type Flow = {
  id: number;
  code: string;
  name: string;
};

type FlowUtil = {
  flow_id: number;
  committed_today: number;
  capacity_per_day: number;
  utilization_pct: number;
  is_full: boolean;
};

type ModelSummary = {
  id: number;
  code?: string | null;
  name?: string | null;
  details_json?: { composition?: MaterialComposition[] | null } | null;
  material_composition?: MaterialComposition[] | null;
};

type SalesOrderSummary = {
  id: number;
  order_no?: string | null;
  customer_name?: string | null;
  customer?: { name?: string | null } | null;
};

type ReservationPlanRow = {
  item_id: number;
  item_sku: string;
  item_name: string;
  composition?: MaterialComposition[] | null;
  unit: string;
  required_quantity: number;
  already_reserved_quantity: number;
  remaining_to_reserve: number;
  available_stock: number;
  shortage: number;
  status: string;
};

type ReservationRow = {
  id: number;
  reservation_no: string;
  item_id: number;
  item_sku?: string | null;
  item_name?: string | null;
  batch_no?: string | null;
  reserved_quantity: number;
  consumed_quantity: number;
  released_quantity: number;
  unit: string;
  status: string;
};

type ReservationSummary = {
  required_quantity: number;
  already_reserved_quantity: number;
  remaining_to_reserve: number;
  shortage: number;
  active_reserved_quantity?: number;
  consumed_quantity?: number;
  released_quantity?: number;
  reservation_count?: number;
};

type ReservationStatus = {
  plan: {
    status: string;
    is_complete: boolean;
    warning?: string | null;
    summary: ReservationSummary;
    rows: ReservationPlanRow[];
  };
  summary: ReservationSummary;
  reservations: ReservationRow[];
};

const PRE_CUTTING_EDIT_STATUSES = new Set(["new", "planning", "pending", "waiting", "ready"]);

function dateInputValue(value?: string | null) {
  return value ? value.slice(0, 10) : "";
}

function formatMaterialUsage(amount?: number | string | null, unit?: string | null) {
  if (amount === null || amount === undefined || amount === "") return "-";
  const parsed = Number(amount);
  if (!Number.isFinite(parsed)) return "-";
  return `${parsed.toLocaleString(undefined, { maximumFractionDigits: 4 })}${unit ? ` ${unit}` : ""}`;
}

function fmtQty(value: number | string | null | undefined) {
  const parsed = Number(value || 0);
  return parsed.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function reservationStatusLabel(status: string, t: (key: string) => string) {
  if (status === "no_bom") return t("reservation.status.noBom");
  if (status === "ready") return t("reservation.status.ready");
  if (status === "shortage") return t("reservation.status.shortage");
  return t("reservation.status.partial");
}

function reservationStatusClass(status: string) {
  if (status === "no_bom") return "border-slate-200 bg-slate-50 text-slate-700";
  if (status === "ready") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "shortage") return "border-red-200 bg-red-50 text-red-700";
  return "border-amber-200 bg-amber-50 text-amber-700";
}

function modelLabel(model: ModelSummary | undefined, id?: number | null) {
  if (!model) return id ? `#${id}` : "-";
  return [model.code, model.name].filter(Boolean).join(" - ") || `#${model.id}`;
}

function salesOrderLabel(order: SalesOrderSummary | undefined, id?: number | null) {
  if (!order) return id ? `#${id}` : "-";
  const customer = order.customer?.name || order.customer_name;
  return [order.order_no || `#${order.id}`, customer].filter(Boolean).join(" - ");
}

function SummaryImage({ label, imageUrl }: { label: string; imageUrl?: string | null }) {
  const src = storageThumbnailUrl(imageUrl, 480);
  if (!src) return null;
  return (
    <a
      href={imagePreviewHref(imageUrl, label)}
      target="_blank"
      rel="noreferrer"
      className="block min-w-0 rounded-md focus:outline-none focus:ring-2 focus:ring-[#2a211c] focus:ring-offset-2"
    >
      <span className="mb-1 block text-xs text-slate-500">{label}</span>
      <span className="flex aspect-[4/3] max-h-64 min-h-40 items-center justify-center overflow-hidden rounded-md border border-[#ecebe3] bg-[#fbfaf7] p-2">
        <img src={src} alt={label} className="h-full w-full object-contain" loading="lazy" />
      </span>
    </a>
  );
}

export default function ProductionOrderDetail() {
  const params = useParams<{ id: string }>();
  const { t } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const canPlan = can(me, "*", "planning.production");
  const canReserveMaterials = can(me, "*", "planning.reserve_materials", "inventory.reservations.create");
  const canReleaseReservations = can(me, "*", "inventory.reservations.release");
  const isAdmin = can(me, "*");
  const id = params.id;
  const isNumericId = /^\d+$/.test(String(id || ""));
  const { data: po, error: poError, isLoading: poLoading, mutate } = useSWR<any>(isNumericId ? `/api/production-orders/${id}` : null, fetcher);
  const { data: reservationStatus, mutate: mutateReservationStatus } = useSWR<ReservationStatus>(
    isNumericId ? `/api/production-orders/${id}/material-reservation-status` : null,
    fetcher,
  );
  const { data: flows } = useSWR<Flow[]>("/api/sewing-flows", fetcher);
  const { data: flowUtil } = useSWR<FlowUtil[]>("/api/sewing-flows/utilization-snapshot", fetcher, { refreshInterval: 60_000 });
  const { data: users } = useSWR<any[]>(canPlan ? "/api/users" : null, fetcher);
  const { data: models } = useSWR<ModelSummary[]>("/api/models", fetcher);
  const { data: salesOrders } = useSWR<SalesOrderSummary[]>("/api/sales-orders?page_size=500", fetcher);
  const utilByFlow = new Map((flowUtil || []).map((u) => [u.flow_id, u]));
  const batchById = new Map<number, BatchMeta>(((po?.batches || []) as BatchMeta[]).map((b) => [b.id, b]));
  const modelById = new Map((models || []).map((m) => [m.id, m]));
  const salesOrderById = new Map((salesOrders || []).map((so) => [so.id, so]));
  const selectedModel = modelById.get(Number(po?.model_id));
  const selectedModelComposition = formatModelComposition(selectedModel);
  const workOrders = (po?.work_orders || []) as WO[];
  const cuttingWO = workOrders.find((w) => w.operation === "cutting");
  const canEditSummary = canPlan && (!cuttingWO || PRE_CUTTING_EDIT_STATUSES.has(String(cuttingWO.status || "")));

  const [editing, setEditing] = useState<WO | null>(null);
  const [edit, setEdit] = useState({ deadline: "", sewing_flow_id: 0, assigned_to: 0 });
  const [editMsg, setEditMsg] = useState("");
  const [summaryEditing, setSummaryEditing] = useState(false);
  const [summaryDraft, setSummaryDraft] = useState({
    model_id: "",
    sales_order_id: "",
    planned_quantity: "",
    deadline: "",
    estimated_material_code: "",
    estimated_material_amount: "",
    estimated_material_unit: "kg",
  });
  const [summaryMsg, setSummaryMsg] = useState("");
  const [summarySaving, setSummarySaving] = useState(false);
  const [openAssignments, setOpenAssignments] = useState<number | null>(null);
  const [repairing, setRepairing] = useState(false);
  const [repairMsg, setRepairMsg] = useState("");
  const [reservationBusy, setReservationBusy] = useState("");
  const [reservationMsg, setReservationMsg] = useState("");

  async function cascade() {
    try { await api.post(`/api/production-orders/${id}/cascade-deadlines`); mutate(); }
    catch (e: any) { await dialogs.notify(e.message); }
  }
  async function blockWO(wid: number) {
    const reason = prompt(t("page.poDetail.blockReasonPrompt"));
    if (!reason) return;
    try { await api.post(`/api/work-orders/${wid}/block`, { reason }); mutate(); }
    catch (e: any) { await dialogs.notify(e.message); }
  }
  async function unblockWO(wid: number) {
    try { await api.post(`/api/work-orders/${wid}/unblock`); mutate(); }
    catch (e: any) { await dialogs.notify(e.message); }
  }

  async function repairTotals() {
    if (!(await dialogs.ask({ message: t("page.poDetail.confirmRepairTotals") }))) return;
    setRepairing(true);
    setRepairMsg("");
    try {
      const r = await api.post(`/api/production-orders/${id}/admin-repair-totals`);
      setRepairMsg(t("page.poDetail.repairFinished", { count: Number(r?.changed_count || 0) }));
      mutate();
    } catch (e: any) {
      setRepairMsg(e.message || t("page.poDetail.repairFailed"));
    } finally {
      setRepairing(false);
    }
  }

  async function autoReserveMaterials() {
    setReservationBusy("auto");
    setReservationMsg("");
    try {
      const result = await api.post(`/api/production-orders/${id}/reserve-materials`, {
        mode: "full_remaining",
        reserve_accessories: true,
        reserve_materials: true,
        reserve_packaging: true,
      });
      setReservationMsg(t("reservation.createdCount", { count: Number(result?.created_count || 0) }));
      mutateReservationStatus();
    } catch (e: any) {
      setReservationMsg(e?.message || t("reservation.actionFailed"));
    } finally {
      setReservationBusy("");
    }
  }

  async function releaseReservation(reservationId: number) {
    setReservationBusy(`release-${reservationId}`);
    setReservationMsg("");
    try {
      await api.post(`/api/inventory/reservations/${reservationId}/release`, {});
      setReservationMsg(t("reservation.released"));
      mutateReservationStatus();
    } catch (e: any) {
      setReservationMsg(e?.message || t("reservation.actionFailed"));
    } finally {
      setReservationBusy("");
    }
  }

  function openEdit(w: WO) {
    setEditing(w);
    setEdit({
      deadline: w.deadline ? w.deadline.slice(0, 10) : "",
      sewing_flow_id: w.sewing_flow_id ?? 0,
      assigned_to: w.assigned_to ?? 0,
    });
    setEditMsg("");
  }

  async function saveAssign(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try {
      await api.patch(`/api/work-orders/${editing.id}`, {
        deadline: edit.deadline ? new Date(edit.deadline).toISOString() : null,
        sewing_flow_id: edit.sewing_flow_id || null,
        assigned_to: edit.assigned_to || null,
      });
      setEditing(null);
      mutate();
    } catch (e: any) { setEditMsg(e.message); }
  }

  function openSummaryEdit() {
    if (!canEditSummary) {
      setSummaryMsg(t("page.poDetail.lockedAfterCuttingStart"));
      return;
    }
    setSummaryDraft({
      model_id: po?.model_id ? String(po.model_id) : "",
      sales_order_id: po?.sales_order_id ? String(po.sales_order_id) : "",
      planned_quantity: po?.planned_quantity === null || po?.planned_quantity === undefined ? "" : String(po.planned_quantity),
      deadline: dateInputValue(po?.deadline),
      estimated_material_code: po?.estimated_material_code ?? "",
      estimated_material_amount: po?.estimated_material_amount === null || po?.estimated_material_amount === undefined
        ? ""
        : String(po.estimated_material_amount),
      estimated_material_unit: po?.estimated_material_unit || "kg",
    });
    setSummaryMsg("");
    setSummaryEditing(true);
  }

  async function saveSummary(e: React.FormEvent) {
    e.preventDefault();
    if (!canEditSummary) {
      setSummaryMsg(t("page.poDetail.lockedAfterCuttingStart"));
      return;
    }

    const modelId = Number(summaryDraft.model_id);
    if (!Number.isInteger(modelId) || modelId <= 0) {
      setSummaryMsg(t("page.poDetail.invalidModel"));
      return;
    }

    const salesOrderText = summaryDraft.sales_order_id.trim();
    const salesOrderId = salesOrderText ? Number(salesOrderText) : null;
    if (salesOrderText && (!Number.isInteger(salesOrderId) || salesOrderId <= 0)) {
      setSummaryMsg(t("page.poDetail.invalidSalesOrder"));
      return;
    }

    const plannedQty = Number(summaryDraft.planned_quantity);
    if (!Number.isInteger(plannedQty) || plannedQty < 0) {
      setSummaryMsg(t("page.poDetail.invalidPlannedQty"));
      return;
    }

    const materialAmountText = summaryDraft.estimated_material_amount.trim();
    const materialAmount = materialAmountText ? Number(materialAmountText) : null;
    if (materialAmountText && (!Number.isFinite(materialAmount) || materialAmount < 0)) {
      setSummaryMsg(t("page.poDetail.invalidMaterialUsage"));
      return;
    }

    setSummarySaving(true);
    setSummaryMsg("");
    try {
      await api.patch(`/api/production-orders/${id}`, {
        model_id: modelId,
        sales_order_id: salesOrderId,
        planned_quantity: plannedQty,
        deadline: summaryDraft.deadline ? new Date(summaryDraft.deadline).toISOString() : null,
        estimated_material_code: summaryDraft.estimated_material_code.trim() || null,
        estimated_material_amount: materialAmount,
        estimated_material_unit: summaryDraft.estimated_material_unit.trim() || null,
      });
      setSummaryEditing(false);
      setSummaryMsg(t("msg.saved"));
      mutate();
    } catch (e: any) {
      setSummaryMsg(e.message);
    } finally {
      setSummarySaving(false);
    }
  }

  if (!isNumericId) {
    return (
      <div className="card p-4 text-sm text-red-700">
        {t("page.productionOrder.invalidId")}
      </div>
    );
  }
  if (poError) {
    return (
      <div className="card p-4 text-sm text-red-700">
        <div>{t("page.productionOrder.loadError")}</div>
        <button className="btn mt-3" onClick={() => mutate()}>{t("common.retry")}</button>
      </div>
    );
  }
  if (poLoading || !po) return <div className="card p-4 text-sm text-slate-500">{t("common.loading")}</div>;
  const orderNo = orderReference(po, po.production_no || `#${po.id}`);

  return (
    <div>
      <PageHeader
        title={t("page.poDetail.title", { productionNo: orderNo, orderNo })}
        subtitle={t("page.poDetail.subtitle", { type: productionTypeLabel(po.production_type, t), status: statusLabel(po.status, t) })}
        actions={canPlan ? (
          <div className="flex gap-2">
            <button className="btn" onClick={cascade} title={t("page.poDetail.cascadeDeadlinesHint")}>{t("page.poDetail.cascadeDeadlines")}</button>
            {isAdmin && (
              <button className="btn" onClick={repairTotals} disabled={repairing} title={t("page.poDetail.repairTotalsHint")}>
                {repairing ? t("page.poDetail.repairing") : t("page.poDetail.repairTotals")}
              </button>
            )}
          </div>
        ) : undefined}
      />
      {repairMsg && <div className="mb-3 text-sm text-slate-600">{repairMsg}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="card p-4">
          <h3 className="font-medium mb-2">{t("page.poDetail.plan")}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.color")}</th><th>{t("field.size")}</th>
                <th>{t("page.poDetail.planned")}</th><th>{t("page.poDetail.completed")}</th>
              </tr>
            </thead>
            <tbody>{po.items?.map((i: any) => <tr key={i.id}><td>{i.color}</td><td>{i.size}</td><td>{i.planned_quantity}</td><td>{i.completed_quantity}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="card p-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h3 className="font-medium">{t("page.poDetail.summary")}</h3>
              {canPlan && !canEditSummary && (
                <div className="mt-1 text-xs text-slate-500">{t("page.poDetail.lockedAfterCuttingStart")}</div>
              )}
            </div>
            {canEditSummary && !summaryEditing && (
              <button type="button" className="btn" onClick={openSummaryEdit}>{t("btn.edit")}</button>
            )}
          </div>

          {summaryEditing ? (
            <form onSubmit={saveSummary} className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="label">{t("field.model")}</label>
                  <select
                    className="input"
                    value={summaryDraft.model_id}
                    onChange={(e) => setSummaryDraft({ ...summaryDraft, model_id: e.target.value })}
                  >
                    <option value="">{t("newso.selectModel")}</option>
                    {po?.model_id && !modelById.has(Number(po.model_id)) && (
                      <option value={po.model_id}>{modelLabel(undefined, po.model_id)}</option>
                    )}
                    {models?.map((m) => (
                      <option key={m.id} value={m.id}>{modelLabel(m, m.id)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">{t("page.poDetail.salesOrder")}</label>
                  <select
                    className="input"
                    value={summaryDraft.sales_order_id}
                    onChange={(e) => setSummaryDraft({ ...summaryDraft, sales_order_id: e.target.value })}
                  >
                    <option value="">{t("page.poDetail.noSalesOrder")}</option>
                    {po?.sales_order_id && !salesOrderById.has(Number(po.sales_order_id)) && (
                      <option value={po.sales_order_id}>{salesOrderLabel(undefined, po.sales_order_id)}</option>
                    )}
                    {salesOrders?.map((so) => (
                      <option key={so.id} value={so.id}>{salesOrderLabel(so, so.id)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">{t("page.poDetail.plannedQty")}</label>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step={1}
                    value={summaryDraft.planned_quantity}
                    onChange={(e) => setSummaryDraft({ ...summaryDraft, planned_quantity: e.target.value })}
                  />
                </div>
                <div>
                  <label className="label">{t("field.deadline")}</label>
                  <input
                    className="input"
                    type="date"
                    value={summaryDraft.deadline}
                    onChange={(e) => setSummaryDraft({ ...summaryDraft, deadline: e.target.value })}
                  />
                </div>
                <div>
                  <label className="label">{t("page.poDetail.estimatedMaterialCode")}</label>
                  <input
                    className="input"
                    value={summaryDraft.estimated_material_code}
                    onChange={(e) => setSummaryDraft({ ...summaryDraft, estimated_material_code: e.target.value })}
                  />
                </div>
                <div>
                  <label className="label">{t("page.poDetail.estimatedMaterialUsage")}</label>
                  <div className="grid grid-cols-[minmax(0,1fr)_5.5rem] gap-2">
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step="0.0001"
                      value={summaryDraft.estimated_material_amount}
                      onChange={(e) => setSummaryDraft({ ...summaryDraft, estimated_material_amount: e.target.value })}
                    />
                    <input
                      className="input"
                      value={summaryDraft.estimated_material_unit}
                      onChange={(e) => setSummaryDraft({ ...summaryDraft, estimated_material_unit: e.target.value })}
                    />
                  </div>
                </div>
              </div>
              {summaryMsg && <div className="text-sm text-red-600">{summaryMsg}</div>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" className="btn" onClick={() => { setSummaryEditing(false); setSummaryMsg(""); }}>
                  {t("btn.cancel")}
                </button>
                <button type="submit" className="btn btn-primary" disabled={summarySaving}>
                  {summarySaving ? t("common.saving") : t("btn.saveChanges")}
                </button>
              </div>
            </form>
          ) : (
          <>
          {(po.model_image_url || po.variant_picture_url) && (
            <div className="mb-3 grid grid-cols-2 gap-3">
              <SummaryImage label={t("page.workOrder.modelPicture")} imageUrl={po.model_image_url} />
              <SummaryImage label={t("page.workOrder.variantPicture")} imageUrl={po.variant_picture_url} />
            </div>
          )}
          <dl className="text-sm space-y-1">
            <div className="flex justify-between gap-3">
              <dt className="text-slate-500">{t("field.model")}</dt>
              <dd className="text-right">
                <div>{modelLabel(selectedModel, po.model_id)}</div>
                {selectedModelComposition && (
                  <div className="mt-1 max-w-[320px] text-xs text-[#56503f]">{selectedModelComposition}</div>
                )}
              </dd>
            </div>
            <div className="flex justify-between gap-3"><dt className="text-slate-500">{t("field.orderNo")}</dt><dd className="text-right">{orderNo}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.poDetail.plannedQty")}</dt><dd>{po.planned_quantity}</dd></div>
            {Number(po.actual_bundle_quantity || 0) > 0 && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.poDetail.actualBundleQuantity")}</dt><dd>{po.actual_bundle_quantity}</dd></div>
            )}
            {Number(po.actual_bundle_count || 0) > 0 && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.poDetail.actualBundles")}</dt><dd>{po.actual_bundle_count}</dd></div>
            )}
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.deadline")}</dt><dd>{po.deadline ? new Date(po.deadline).toLocaleDateString() : "—"}</dd></div>
            <div className="flex justify-between border-t border-[#ecebe3] pt-2">
              <dt className="text-slate-500">{t("page.poDetail.estimatedMaterialCode")}</dt>
              <dd>{po.estimated_material_code || "-"}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">{t("page.poDetail.estimatedMaterialUsage")}</dt>
              <dd>{formatMaterialUsage(po.estimated_material_amount, po.estimated_material_unit)}</dd>
            </div>
          </dl>
          {summaryMsg && (
            <div className={`mt-3 text-sm ${summaryMsg === t("msg.saved") ? "text-emerald-700" : "text-red-600"}`}>
              {summaryMsg}
            </div>
          )}
          </>
          )}
        </div>
      </div>

      <section className="card mb-6 overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-[#ecebe3] p-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="app-card-title">{t("reservation.title")}</h3>
              {reservationStatus && (
                <span className={`rounded-md border px-2 py-0.5 text-xs font-medium ${reservationStatusClass(reservationStatus.plan.status)}`}>
                  {reservationStatusLabel(reservationStatus.plan.status, t)}
                </span>
              )}
            </div>
            <div className="mt-1 text-sm text-[#6f684f]">{t("reservation.productionSubtitle")}</div>
          </div>
          {canReserveMaterials && (
            <button type="button" className="btn btn-primary" onClick={autoReserveMaterials} disabled={reservationBusy === "auto"}>
              <PackageCheck className="h-4 w-4" />
              {reservationBusy === "auto" ? t("common.saving") : t("reservation.autoReserve")}
            </button>
          )}
        </div>
        {reservationStatus ? (
          <div className="space-y-4 p-4">
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div>
                <div className="text-[#8a8472]">{t("field.required")}</div>
                <div className="mono font-semibold">{fmtQty(reservationStatus.summary.required_quantity)}</div>
              </div>
              <div>
                <div className="text-[#8a8472]">{t("field.reserved")}</div>
                <div className="mono font-semibold">{fmtQty(reservationStatus.summary.already_reserved_quantity)}</div>
              </div>
              <div>
                <div className="text-[#8a8472]">{t("field.remaining")}</div>
                <div className="mono font-semibold">{fmtQty(reservationStatus.summary.remaining_to_reserve)}</div>
              </div>
              <div>
                <div className="text-[#8a8472]">{t("field.shortage")}</div>
                <div className={`mono font-semibold ${Number(reservationStatus.summary.shortage || 0) > 0 ? "text-red-700" : ""}`}>
                  {fmtQty(reservationStatus.summary.shortage)}
                </div>
              </div>
            </div>
            {reservationStatus.plan.warning && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                {t("reservation.cuttingWarning")}
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="table text-sm">
                <thead>
                  <tr>
                    <th>{t("field.item")}</th>
                    <th>{t("field.required")}</th>
                    <th>{t("field.reserved")}</th>
                    <th>{t("field.available")}</th>
                    <th>{t("field.shortage")}</th>
                  </tr>
                </thead>
                <tbody>
                  {reservationStatus.plan.rows.map((row) => (
                    <tr key={`${row.item_id}-${row.unit}`}>
                      <td>
                        <div className="mono font-semibold text-[#14110b]">{row.item_sku}</div>
                        <div className="max-w-[260px] truncate text-xs text-[#8a8472]">{row.item_name}</div>
                        {formatComposition(row.composition) && (
                          <div className="max-w-[260px] truncate text-xs text-[#56503f]">{formatComposition(row.composition)}</div>
                        )}
                      </td>
                      <td className="mono">{fmtQty(row.required_quantity)} {row.unit}</td>
                      <td className="mono">{fmtQty(row.already_reserved_quantity)} {row.unit}</td>
                      <td className="mono">{fmtQty(row.available_stock)} {row.unit}</td>
                      <td className={`mono ${Number(row.shortage || 0) > 0 ? "text-red-700" : ""}`}>{fmtQty(row.shortage)} {row.unit}</td>
                    </tr>
                  ))}
                  {reservationStatus.plan.rows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="text-sm text-[#8a8472]">{t("reservation.noBomRows")}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="overflow-x-auto border-t border-[#ecebe3] pt-4">
              <div className="mb-2 text-sm font-semibold text-[#14110b]">{t("reservation.reservedBatches")}</div>
              <table className="table text-sm">
                <thead>
                  <tr>
                    <th>{t("field.batch")}</th>
                    <th>{t("field.item")}</th>
                    <th>{t("field.reserved")}</th>
                    <th>{t("reservation.consumed")}</th>
                    <th>{t("reservation.releasedQty")}</th>
                    <th>{t("common.status")}</th>
                    <th>{t("field.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {reservationStatus.reservations.map((reservation) => (
                    <tr key={reservation.id}>
                      <td className="mono">{reservation.batch_no || "-"}</td>
                      <td>{reservation.item_sku || reservation.item_id}</td>
                      <td className="mono">{fmtQty(reservation.reserved_quantity)} {reservation.unit}</td>
                      <td className="mono">{fmtQty(reservation.consumed_quantity)} {reservation.unit}</td>
                      <td className="mono">{fmtQty(reservation.released_quantity)} {reservation.unit}</td>
                      <td><span className="badge">{statusLabel(reservation.status, t)}</span></td>
                      <td>
                        {canReleaseReservations && ["reserved", "partially_consumed"].includes(reservation.status) ? (
                          <button
                            type="button"
                            className="btn h-8 px-2 text-xs"
                            onClick={() => releaseReservation(reservation.id)}
                            disabled={reservationBusy === `release-${reservation.id}`}
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            {t("btn.releaseReservation")}
                          </button>
                        ) : "-"}
                      </td>
                    </tr>
                  ))}
                  {reservationStatus.reservations.length === 0 && (
                    <tr>
                      <td colSpan={7} className="text-sm text-[#8a8472]">{t("reservation.noReservations")}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {reservationMsg && <div className="text-sm text-[#56503f]">{reservationMsg}</div>}
          </div>
        ) : (
          <div className="p-4 text-sm text-[#8a8472]">{t("common.loading")}</div>
        )}
      </section>

      <div className="card p-4">
        <h3 className="font-medium mb-2">{t("page.poDetail.workOrders")}</h3>
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.batch")}</th>
                <th>{t("page.poDetail.op")}</th>
                <th>{t("common.status")}</th>
                <th>{t("field.input")}</th>
                <th>{t("field.output")}</th>
                <th>{t("field.failed")}</th>
                <th>{t("field.deadline2")}</th>
                <th>{t("field.line")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {po.work_orders?.map((w: WO) => (
                <>
                  <tr key={w.id} className={w.is_blocked ? "bg-red-50" : ""}>
                    <td>
                      {w.production_batch_id
                        ? (() => {
                            const b = batchById.get(w.production_batch_id);
                            return b ? formatBatchLabel(b, po?.id) : "-";
                          })()
                        : "-"}
                    </td>
                    <td className="font-medium">
                      {operationLabel(w.operation, t)}
                      {w.is_blocked && (
                        <div className="text-xs text-red-700" title={w.block_reason ?? ""}>⛔ {t("status.blocked")}</div>
                      )}
                    </td>
                    <td><span className="badge">{statusLabel(w.status, t)}</span></td>
                    <td>{w.actual_input_qty}</td>
                    <td>{w.actual_output_qty}</td>
                    <td>{w.failed_qty}</td>
                    <td>{w.deadline ? new Date(w.deadline).toLocaleDateString() : "—"}</td>
                    <td>{flows?.find((f) => f.id === w.sewing_flow_id)?.name ?? "—"}</td>
                    <td className="flex gap-2 flex-wrap">
                      {canPlan && w.operation === "sewing" && (
                        <button className="text-slate-700 hover:underline" onClick={() => openEdit(w)}>{t("btn.assign")}</button>
                      )}
                      {!w.is_blocked
                        ? <button className="text-red-600 hover:underline" onClick={() => blockWO(w.id)}>{t("btn.block")}</button>
                        : <button className="text-amber-700 hover:underline" onClick={() => unblockWO(w.id)}>{t("btn.unblock")}</button>}
                      {w.operation === "sewing" && (
                        <button className="text-slate-600 hover:underline" onClick={() => setOpenAssignments(openAssignments === w.id ? null : w.id)}>
                          {openAssignments === w.id ? t("btn.hideSplit") : t("btn.split")}
                        </button>
                      )}
                      {w.operation === "cutting" && <Link href={`/work-orders/${w.id}/cutting`} className="text-brand-600 hover:underline">{t("dash.cutting")}</Link>}
                      {w.operation === "printing" && <Link href={`/work-orders/${w.id}/printing`} className="text-brand-600 hover:underline">{t("dash.printing")}</Link>}
                      {w.operation === "sewing" && <Link href={`/work-orders/${w.id}/sewing`} className="text-brand-600 hover:underline">{t("dash.sewing")}</Link>}
                      {w.operation === "packaging" && <Link href={`/work-orders/${w.id}/packaging`} className="text-brand-600 hover:underline">{t("dash.packaging")}</Link>}
                    </td>
                  </tr>
                  {w.operation === "sewing" && openAssignments === w.id && (
                    <tr key={`${w.id}-assignments`}>
                      <td colSpan={9} className="bg-slate-50 p-3">
                        <SewingAssignmentsPanel woId={w.id} plannedQty={w.planned_input_qty} flows={flows ?? []} utilByFlow={utilByFlow} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing ? `${operationLabel(editing.operation, t)} #${editing.id}` : ""}>
        <form onSubmit={saveAssign} className="space-y-3">
          <div>
            <label className="label">{t("field.deadline2")}</label>
            <input className="input" type="date" value={edit.deadline} onChange={(e) => setEdit({ ...edit, deadline: e.target.value })} />
          </div>
          {editing?.operation === "sewing" && (
            <div>
              <label className="label">{t("field.line")}</label>
              <select className="input" value={edit.sewing_flow_id} onChange={(e) => setEdit({ ...edit, sewing_flow_id: Number(e.target.value) })}>
                <option value={0}>—</option>
                {flows?.map((f) => {
                  const u = utilByFlow.get(f.id);
                  const isFull = !!u?.is_full;
                  return (
                    <option key={f.id} value={f.id} disabled={isFull}>
                      {f.name} ({f.code}){isFull ? ` (FULL ${u?.utilization_pct ?? 100}%)` : ""}
                    </option>
                  );
                })}
              </select>
              {edit.sewing_flow_id > 0 && utilByFlow.get(edit.sewing_flow_id)?.is_full && (
                <div className="mt-1 text-xs text-red-600">{t("msg.lineFull")}</div>
              )}
            </div>
          )}
          <div>
            <label className="label">{t("field.user")}</label>
            <select className="input" value={edit.assigned_to} onChange={(e) => setEdit({ ...edit, assigned_to: Number(e.target.value) })}>
              <option value={0}>—</option>
              {users?.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.email})</option>)}
            </select>
          </div>
          {editMsg && <div className="text-sm text-red-600">{editMsg}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={() => setEditing(null)}>{t("btn.cancel")}</button>
            <button type="submit" className="btn btn-primary">{t("btn.saveChanges")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}


function SewingAssignmentsPanel({
  woId,
  plannedQty,
  flows,
  utilByFlow,
}: {
  woId: number;
  plannedQty: number;
  flows: Flow[];
  utilByFlow: Map<number, FlowUtil>;
}) {
  const { t } = useT();
  const dialogs = useDialogs();
  const { data, mutate } = useSWR<Assignment[]>(`/api/work-orders/${woId}/assignments`, fetcher);
  const [draft, setDraft] = useState<{ sewing_flow_id: number; quantity: NumberInputValue; planned_start: string; planned_end: string }>({ sewing_flow_id: 0, quantity: "", planned_start: "", planned_end: "" });
  const [msg, setMsg] = useState("");
  const committed = (data || []).reduce((s, a) => s + a.quantity, 0);
  const remaining = Math.max(0, plannedQty - committed);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    if (draft.sewing_flow_id > 0 && utilByFlow.get(draft.sewing_flow_id)?.is_full) {
      setMsg(t("msg.selectedLineFull"));
      return;
    }
    try {
      await api.post(`/api/work-orders/${woId}/assignments`, {
        work_order_id: woId,
        sewing_flow_id: draft.sewing_flow_id,
        quantity: numberOrZero(draft.quantity),
        planned_start: draft.planned_start ? new Date(draft.planned_start).toISOString() : null,
        planned_end: draft.planned_end ? new Date(draft.planned_end).toISOString() : null,
      });
      setDraft({ sewing_flow_id: 0, quantity: "", planned_start: "", planned_end: "" });
      mutate();
    } catch (e: any) { setMsg(e.message); }
  }
  async function del(aid: number) {
    if (!(await dialogs.ask({ message: t("confirm.deleteAssignment"), tone: "danger" }))) return;
    try { await api.del(`/api/sewing-assignments/${aid}`); mutate(); }
    catch (e: any) { await dialogs.notify(e.message); }
  }

  return (
    <div>
      <div className="text-xs font-medium text-slate-500 uppercase mb-2">
        {t("page.poDetail.splitSummary", { committed, planned: plannedQty, remaining })}
      </div>
      <table className="table text-xs">
        <thead>
          <tr><th>{t("field.line")}</th><th>{t("field.qty")}</th><th>{t("page.poDetail.done")}</th><th>{t("field.plannedStart")}</th><th>{t("field.plannedEnd")}</th><th>{t("common.status")}</th><th></th></tr>
        </thead>
        <tbody>
          {(data || []).map((a) => (
            <tr key={a.id}>
              <td>{flows.find((f) => f.id === a.sewing_flow_id)?.name ?? a.sewing_flow_id}</td>
              <td>{a.quantity}</td>
              <td>{a.completed_qty}</td>
              <td>{a.planned_start ? new Date(a.planned_start).toLocaleDateString() : "—"}</td>
              <td>{a.planned_end ? new Date(a.planned_end).toLocaleDateString() : "—"}</td>
              <td><span className="badge">{statusLabel(a.status, t)}</span></td>
              <td><button onClick={() => del(a.id)} className="text-red-600 hover:underline">{t("tasks.delete")}</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <form onSubmit={add} className="grid grid-cols-1 md:grid-cols-6 gap-2 mt-3">
        <select className="input" value={draft.sewing_flow_id} onChange={(e) => setDraft({ ...draft, sewing_flow_id: Number(e.target.value) })} required>
          <option value={0}>{t("ph.pickLine")}</option>
          {flows.map((f) => {
            const u = utilByFlow.get(f.id);
            const isFull = !!u?.is_full;
            return (
              <option key={f.id} value={f.id} disabled={isFull}>
                {f.name} ({f.code}){isFull ? ` (FULL ${u?.utilization_pct ?? 100}%)` : ""}
              </option>
            );
          })}
        </select>
        <input className="input" type="number" placeholder={t("field.qty")} value={draft.quantity} onChange={(e) => setDraft({ ...draft, quantity: parseNumberInput(e.target.value) })} required />
        <input className="input" type="date" value={draft.planned_start} onChange={(e) => setDraft({ ...draft, planned_start: e.target.value })} />
        <input className="input" type="date" value={draft.planned_end} onChange={(e) => setDraft({ ...draft, planned_end: e.target.value })} />
        <button className="btn btn-primary md:col-span-2" disabled={draft.sewing_flow_id > 0 && !!utilByFlow.get(draft.sewing_flow_id)?.is_full}>
          {t("btn.addAssignment")}
        </button>
        {draft.sewing_flow_id > 0 && utilByFlow.get(draft.sewing_flow_id)?.is_full && (
          <div className="text-sm text-red-600 md:col-span-6">{t("msg.selectedLineFull")}</div>
        )}
        {msg && <div className="text-sm text-red-600 md:col-span-6">{msg}</div>}
      </form>
    </div>
  );
}


