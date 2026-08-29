"use client";
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { orderReference } from "@/lib/orderRef";
import { formatBatchLabel } from "@/lib/batchSerial";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import { useMe } from "@/lib/auth";

type Flow = {
  id: number;
  factory_code: string;
  name: string;
  code: string;
  description: string | null;
  capacity_per_day: number;
  is_active: boolean;
  active_work_orders: number;
  planned_units: number;
  completed_units: number;
};

type WO = {
  id: number;
  order_no?: string | null;
  production_no?: string | null;
  sales_order_no?: string | null;
  production_order_id: number;
  production_batch_id?: number | null;
  assignment_batch_id?: number | null;
  batch_no?: string | null;
  batch_name?: string | null;
  batch_index?: number | null;
  batch_planned_quantity?: number | null;
  sewing_assignment_id?: number | null;
  operation: string;
  status: string;
  planned_input_qty: number;
  planned_output_qty: number;
  passed_qty: number;
  received_bundle_count?: number;
  received_bundle_qty?: number;
  assigned_qty?: number;
  assignable_qty?: number;
  model_no?: string | null;
  model_image_url?: string | null;
  material_image_url?: string | null;
  deadline: string | null;
  sewing_flow_id: number | null;
};

function effectiveSewingQty(workOrder: WO | null | undefined) {
  if (!workOrder) return 0;
  return Math.max(
    0,
    Number(workOrder.batch_planned_quantity || 0),
    Number(workOrder.planned_input_qty || 0),
    Number(workOrder.planned_output_qty || 0),
    Number(workOrder.received_bundle_qty || 0),
  );
}

function assignmentBatchId(workOrder: WO | null | undefined) {
  if (!workOrder) return null;
  const raw = workOrder.assignment_batch_id ?? workOrder.production_batch_id ?? null;
  const id = Number(raw || 0);
  return id > 0 ? id : null;
}

function sewingBatchLabel(workOrder: WO | null | undefined) {
  const batchId = assignmentBatchId(workOrder);
  if (!workOrder || !batchId) return "";
  return formatBatchLabel(
    {
      batch_no: workOrder.batch_no,
      name: workOrder.batch_name,
      batch_index: workOrder.batch_index,
    },
    workOrder.production_order_id,
  );
}

function workOrderRowKey(workOrder: WO) {
  return `${workOrder.id}:${workOrder.sewing_assignment_id || "wo"}:${assignmentBatchId(workOrder) || "order"}`;
}

function formatDeadline(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString();
}

function WorkOrderMiniRow({
  workOrder,
  showActions = false,
  isBusy = false,
  onAssign,
  onMove,
  showImage = false,
  showReceivedQty = false,
}: {
  workOrder: WO;
  showActions?: boolean;
  isBusy?: boolean;
  onAssign?: (wo: WO) => void;
  onMove?: (wo: WO) => void;
  showImage?: boolean;
  showReceivedQty?: boolean;
}) {
  const { t } = useT();
  const batchLabel = sewingBatchLabel(workOrder);
  const qtyDone = showReceivedQty ? Number(workOrder.received_bundle_qty || 0) : Number(workOrder.passed_qty || 0);
  const qtyPlanned = showReceivedQty ? effectiveSewingQty(workOrder) : Number(workOrder.planned_output_qty || workOrder.planned_input_qty || 0);
  if (showImage) {
    return (
      <div className="grid min-w-[390px] grid-cols-[48px_minmax(74px,1fr)_minmax(68px,0.7fr)_minmax(70px,0.7fr)_82px] items-center gap-2 border-b border-[#ecebe3] px-2 py-3 text-xs last:border-b-0">
        <FabricThumb workOrder={workOrder} />
        <div className="min-w-0">
          <Link
            href={`/production-orders/${workOrder.production_order_id}`}
            className="block min-w-0 break-words font-medium text-brand-600 hover:underline"
            title={orderReference(workOrder, `#${workOrder.production_order_id}`)}
          >
            {orderReference(workOrder, `#${workOrder.production_order_id}`)}
          </Link>
          {workOrder.model_no && (
            <div className="mt-1 break-words text-[11px] font-medium text-[#494538]">
              {t("field.modelNo")}: {workOrder.model_no}
            </div>
          )}
          {batchLabel && <div className="mt-1 break-words text-[11px] text-[#6d6655]">{batchLabel}</div>}
          <span className="badge mt-1 max-w-full justify-center px-2 py-1 leading-tight">{statusLabel(workOrder.status, t)}</span>
        </div>
        <div className="text-right tabular-nums text-[#14110b]">
          {qtyDone} / {qtyPlanned}
        </div>
        <div className="text-right tabular-nums text-[#14110b]">
          {formatDeadline(workOrder.deadline)}
        </div>
        <div className="flex flex-col gap-1">
          {workOrder.sewing_assignment_id && onMove && (
            <button
              type="button"
              className="btn h-7 w-full px-2 text-[11px]"
              onClick={() => onMove(workOrder)}
              disabled={isBusy}
            >
              {isBusy ? t("common.loading") : t("btn.move")}
            </button>
          )}
          {showActions && (
            <button
              type="button"
              className="btn h-7 w-full px-2 text-[11px]"
              onClick={() => onAssign?.(workOrder)}
              disabled={isBusy}
            >
              {isBusy ? t("common.loading") : t("btn.assign")}
            </button>
          )}
          <Link href={`/work-orders/${workOrder.id}/sewing`} className="btn h-7 w-full px-2 text-[11px]">
            {t("btn.open")}
          </Link>
        </div>
      </div>
    );
  }
  return (
    <div className="grid min-w-[390px] grid-cols-[minmax(64px,0.9fr)_minmax(70px,0.8fr)_minmax(64px,0.8fr)_minmax(72px,0.75fr)_82px] items-center gap-2 border-b border-[#ecebe3] px-2 py-3 text-xs last:border-b-0">
      <div className="min-w-0">
        <Link
          href={`/production-orders/${workOrder.production_order_id}`}
          className="block min-w-0 break-words font-medium text-brand-600 hover:underline"
          title={orderReference(workOrder, `#${workOrder.production_order_id}`)}
        >
          {orderReference(workOrder, `#${workOrder.production_order_id}`)}
        </Link>
        {batchLabel && <div className="mt-1 min-w-0 break-words text-[11px] text-[#6d6655]">{batchLabel}</div>}
      </div>
      <div className="min-w-0">
        <span className="badge max-w-full justify-center px-2 py-1 leading-tight">{statusLabel(workOrder.status, t)}</span>
      </div>
      <div className="text-right tabular-nums text-[#14110b]">
        {qtyDone} / {qtyPlanned}
      </div>
      <div className="text-right tabular-nums text-[#14110b]">
        {formatDeadline(workOrder.deadline)}
      </div>
      <div className="flex flex-col gap-1">
        {workOrder.sewing_assignment_id && onMove && (
          <button
            type="button"
            className="btn h-7 w-full px-2 text-[11px]"
            onClick={() => onMove(workOrder)}
            disabled={isBusy}
          >
            {isBusy ? t("common.loading") : t("btn.move")}
          </button>
        )}
        {showActions && (
          <button
            type="button"
            className="btn h-7 w-full px-2 text-[11px]"
            onClick={() => onAssign?.(workOrder)}
            disabled={isBusy}
          >
            {isBusy ? t("common.loading") : t("btn.assign")}
          </button>
        )}
        <Link href={`/work-orders/${workOrder.id}/sewing`} className="btn h-7 w-full px-2 text-[11px]">
          {t("btn.open")}
        </Link>
      </div>
    </div>
  );
}

function FabricThumb({ workOrder }: { workOrder: WO }) {
  const { t } = useT();
  const imageUrl = workOrder.material_image_url || "";
  const src = storageThumbnailUrl(imageUrl, 160);
  const label = orderReference(workOrder, `#${workOrder.production_order_id}`);
  if (!src) {
    return (
      <div className="flex h-12 w-12 items-center justify-center rounded-md border border-dashed border-[#d8d1bf] bg-[#faf9f5] text-center text-[9px] leading-3 text-slate-400">
        {t("page.workOrder.noImage")}
      </div>
    );
  }
  return (
    <a href={imagePreviewHref(imageUrl, label)} target="_blank" rel="noreferrer" className="h-12 w-12 overflow-hidden rounded-md border border-[#ecebe3] bg-[#f8f7f3]">
      <img src={src} alt={label} className="h-full w-full object-contain" loading="lazy" />
    </a>
  );
}

function WorkOrderMiniHeader({ showImage = false, showReceivedQty = false }: { showImage?: boolean; showReceivedQty?: boolean }) {
  const { t } = useT();
  if (showImage) {
    return (
      <div className="grid min-w-[390px] grid-cols-[48px_minmax(74px,1fr)_minmax(68px,0.7fr)_minmax(70px,0.7fr)_82px] gap-2 bg-[#f1efe8] px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[#8a8472]">
        <div>{t("field.picture")}</div>
        <div className="min-w-0">{t("field.orderNo")}</div>
        <div className="text-right">{showReceivedQty ? t("field.received") : t("field.passed")}/{t("page.sewingFlows.plannedUnits")}</div>
        <div className="text-right">{t("field.deadline2")}</div>
        <div className="text-right">{t("field.actions")}</div>
      </div>
    );
  }
  return (
    <div className="grid min-w-[390px] grid-cols-[minmax(64px,0.9fr)_minmax(70px,0.8fr)_minmax(64px,0.8fr)_minmax(72px,0.75fr)_82px] gap-2 bg-[#f1efe8] px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[#8a8472]">
      <div className="min-w-0">{t("field.orderNo")}</div>
      <div>{t("common.status")}</div>
      <div className="text-right">{t("field.passed")}/{t("page.sewingFlows.plannedUnits")}</div>
      <div className="text-right">{t("field.deadline2")}</div>
      <div className="text-right">{t("field.actions")}</div>
    </div>
  );
}

export default function SewingFlowsPage() {
  const { t } = useT();
  const { me } = useMe();
  const searchParams = useSearchParams();
  const requestedFactory = (searchParams.get("factory") || me?.factory_code || "MIL").toUpperCase();
  const factoryCode = requestedFactory === "BST" || requestedFactory === "ECO" ? requestedFactory : "MIL";
  const factoryName = factoryCode === "BST" ? "Besttex" : factoryCode === "ECO" ? "Eco Cotton" : "Milana";
  const flowsUrl = `/api/sewing-flows?factory_code=${factoryCode}`;
  const { data: flows } = useSWR<Flow[]>(flowsUrl, fetcher, { refreshInterval: 10_000 });
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const visibleFlows = flows || [];

  return (
    <div>
      <PageHeader title={`${factoryName} - ${t("page.sewingFlows.title")}`} subtitle={t("page.sewingFlows.subtitle")} />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {visibleFlows.map((f) => {
          const isExpanded = !!expanded[f.id];
          const pctDone = f.planned_units > 0 ? Math.min(100, Math.round((100 * f.completed_units) / f.planned_units)) : 0;
          return (
            <div key={f.id} className="card p-4">
              <div className="mb-2 flex items-start justify-between">
                <div>
                  <div className="text-lg font-semibold text-slate-900">{f.name}</div>
                  <div className="text-xs text-slate-500"><code>{f.code}</code></div>
                </div>
                <span className={`badge ${f.is_active ? "badge-green" : "badge-red"}`}>
                  {f.is_active ? t("field.active") : t("field.inactive")}
                </span>
              </div>
              <dl className="mb-3 space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt className="text-slate-500">{t("page.sewingFlows.activeWOs")}</dt>
                  <dd className="font-medium">{f.active_work_orders}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">{t("page.sewingFlows.plannedUnits")}</dt>
                  <dd>{f.planned_units}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">{t("page.sewingFlows.completedUnits")}</dt>
                  <dd>{f.completed_units}</dd>
                </div>
              </dl>
              <div className="mb-2 h-2 w-full overflow-hidden rounded bg-slate-100" title={`${pctDone}% done`}>
                <div className="h-full bg-brand-500" style={{ width: `${pctDone}%` }} />
              </div>
              <button
                type="button"
                className="btn w-full justify-center"
                onClick={() => setExpanded((prev) => ({ ...prev, [f.id]: !prev[f.id] }))}
              >
                {isExpanded
                  ? t("btn.cancel")
                  : (f.active_work_orders > 0 ? t("page.sewingFlows.assigned") : t("page.sewingFlows.readyForWork"))}
              </button>
              {isExpanded && (
                <FlowDetail
                  flow={f}
                  flows={visibleFlows}
                  factoryCode={factoryCode}
                  flowsUrl={flowsUrl}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FlowDetail({
  flow,
  flows,
  factoryCode,
  flowsUrl,
}: {
  flow: Flow;
  flows: Flow[];
  factoryCode: string;
  flowsUrl: string;
}) {
  const { t } = useT();
  const { mutate: mutateGlobal } = useSWRConfig();
  const flowId = flow.id;
  const assignedUrl = `/api/sewing-flows/${flowId}/work-orders?only_active=true`;
  const { data: wos, mutate: mutateAssigned } = useSWR<WO[]>(assignedUrl, fetcher);
  const { data: availableWos, mutate: mutateAvailableWos } = useSWR<WO[]>(
    `/api/work-orders?operation=sewing&only_active=true&only_received_sewing=true&sewing_factory_code=${factoryCode}`,
    fetcher,
  );
  const [claimingKey, setClaimingKey] = useState<string | null>(null);
  const [loadingPickKey, setLoadingPickKey] = useState<string | null>(null);
  const [movingAssignmentId, setMovingAssignmentId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [moveMsg, setMoveMsg] = useState("");
  const [pick, setPick] = useState<{
    wo: WO | null;
    qty: NumberInputValue;
    maxQty: number;
    productionBatchId: number | null;
    batchLabel: string;
  }>({ wo: null, qty: "", maxQty: 0, productionBatchId: null, batchLabel: "" });
  const [movePick, setMovePick] = useState<{ wo: WO | null; destinationFlowId: number | null }>({
    wo: null,
    destinationFlowId: null,
  });
  const destinationFlows = flows.filter((candidate) => candidate.is_active && candidate.id !== flowId);

  function closeMove() {
    setMovePick({ wo: null, destinationFlowId: null });
    setMoveMsg("");
  }

  function openMove(wo: WO) {
    if (!wo.sewing_assignment_id) return;
    setMoveMsg("");
    setMovePick({ wo, destinationFlowId: null });
  }

  async function moveWork() {
    const assignmentId = movePick.wo?.sewing_assignment_id;
    const destinationFlowId = movePick.destinationFlowId;
    if (!assignmentId || !destinationFlowId) return;
    setMoveMsg("");
    setMovingAssignmentId(assignmentId);
    try {
      await api.patch(`/api/sewing-assignments/${assignmentId}`, {
        sewing_flow_id: destinationFlowId,
      });
      closeMove();
      await Promise.all([
        mutateAssigned(),
        mutateAvailableWos(),
        mutateGlobal(`/api/sewing-flows/${destinationFlowId}/work-orders?only_active=true`),
        mutateGlobal(flowsUrl),
      ]);
    } catch (e: any) {
      setMoveMsg(e.message);
    } finally {
      setMovingAssignmentId(null);
    }
  }

  async function openPick(wo: WO) {
    const rowKey = workOrderRowKey(wo);
    const batchId = assignmentBatchId(wo);
    setLoadingPickKey(rowKey);
    setMsg("");
    try {
      let remainingAssignable = Math.max(0, Number(wo.assignable_qty || 0));
      if (remainingAssignable <= 0) {
        const assignments = await api.get<any[]>(`/api/work-orders/${wo.id}/assignments`);
        const assignedTotal = (assignments || []).reduce((sum, a) => {
          const assignmentStatus = String(a?.status || "");
          if (!["planned", "in_progress", "completed"].includes(assignmentStatus)) return sum;
          const assignmentBatchId = Number(a?.production_batch_id || 0) || null;
          if ((assignmentBatchId || null) !== (batchId || null)) return sum;
          return sum + Number(a?.quantity || 0);
        }, 0);
        const planned = Number(wo.batch_planned_quantity || wo.planned_input_qty || wo.planned_output_qty || 0);
        const receivedQty = Math.max(0, Number(wo.received_bundle_qty || 0));
        const availableFromReceived = receivedQty > 0 ? receivedQty : planned;
        remainingAssignable = Math.max(0, availableFromReceived - assignedTotal);
      }
      if (remainingAssignable <= 0) {
        setMsg(`${t("field.qty")} <= 0`);
        return;
      }
      setPick({
        wo,
        qty: remainingAssignable > 0 ? remainingAssignable : 1,
        maxQty: remainingAssignable,
        productionBatchId: batchId,
        batchLabel: sewingBatchLabel(wo),
      });
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setLoadingPickKey(null);
    }
  }

  async function takeWork() {
    if (!pick.wo) return;
    const wid = pick.wo.id;
    const remainingWo = Math.max(0, Number(pick.maxQty || 0));
    const qty = numberOrZero(pick.qty);
    if (qty <= 0) {
      setMsg(t("field.qty") + " > 0");
      return;
    }
    if (remainingWo > 0 && qty > remainingWo) {
      setMsg(`${t("field.qty")} <= ${remainingWo}`);
      return;
    }
    setMsg("");
    setClaimingKey(workOrderRowKey(pick.wo));
    try {
      const now = new Date();
      const nextDay = new Date(now.getTime() + 24 * 60 * 60 * 1000);
      await api.post(`/api/work-orders/${wid}/assignments`, {
        work_order_id: wid,
        production_batch_id: pick.productionBatchId,
        sewing_flow_id: flowId,
        quantity: qty,
        planned_start: now.toISOString(),
        planned_end: nextDay.toISOString(),
      });
      setPick({ wo: null, qty: "", maxQty: 0, productionBatchId: null, batchLabel: "" });
      await Promise.all([mutateAssigned(), mutateAvailableWos(), mutateGlobal(flowsUrl)]);
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setClaimingKey(null);
    }
  }

  if (!wos || !availableWos) return <div className="mt-3 text-xs text-slate-500">{t("common.loading")}</div>;

  return (
    <div className="mt-3 space-y-3">
      {wos.length > 0 ? (
        <div className="overflow-x-auto rounded-md border border-[#e3dfd3]">
          <WorkOrderMiniHeader showImage />
          {wos.map((w) => (
            <WorkOrderMiniRow
              key={workOrderRowKey(w)}
              workOrder={w}
              showImage
              isBusy={movingAssignmentId === w.sewing_assignment_id}
              onMove={openMove}
            />
          ))}
        </div>
      ) : (
        <div className="text-xs text-slate-500">{t("page.sewingFlows.empty")}</div>
      )}

      <div className="rounded-md border border-[#e3dfd3] p-3">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{t("page.sewingFlows.assignableWork")}</div>
        {availableWos.length === 0 ? (
          <div className="text-xs text-slate-400">{t("page.sewingFlows.noUnassignedWork")}</div>
        ) : (
          <div className="overflow-x-auto rounded-md border border-[#e3dfd3]">
            <WorkOrderMiniHeader showImage showReceivedQty />
            {availableWos.map((w) => {
              const rowKey = workOrderRowKey(w);
              return (
                <WorkOrderMiniRow
                  key={rowKey}
                  workOrder={w}
                  showActions
                  showImage
                  showReceivedQty
                  isBusy={claimingKey === rowKey || loadingPickKey === rowKey}
                  onAssign={openPick}
                />
              );
            })}
          </div>
        )}
        {msg && <div className="mt-2 text-xs text-red-600">{msg}</div>}
      </div>

      <Modal open={!!pick.wo} onClose={() => setPick({ wo: null, qty: "", maxQty: 0, productionBatchId: null, batchLabel: "" })} title={t("btn.assign")}>
        <div className="space-y-3">
          <div className="text-xs text-slate-500">
            {pick.wo ? orderReference(pick.wo, `#${pick.wo.production_order_id}`) : ""}
          </div>
          {pick.batchLabel && (
            <div className="text-xs text-slate-500">
              {t("field.batch")}: {pick.batchLabel}
            </div>
          )}
          <div className="text-xs text-slate-500">
            {t("field.passed")}/{t("page.sewingFlows.plannedUnits")}: {pick.wo ? `${pick.wo.passed_qty}/${effectiveSewingQty(pick.wo)}` : "-"}
          </div>
          <div className="text-xs text-slate-500">
            {t("field.available")}: {pick.maxQty}
          </div>
          <div>
            <label className="label">{t("field.qty")}</label>
            <input
              className="input"
              type="number"
              min={1}
              value={pick.qty}
              onChange={(e) => setPick((prev) => ({ ...prev, qty: parseNumberInput(e.target.value) }))}
            />
          </div>
          {msg && <div className="text-xs text-red-600">{msg}</div>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn" onClick={() => setPick({ wo: null, qty: "", maxQty: 0, productionBatchId: null, batchLabel: "" })}>{t("btn.cancel")}</button>
            <button type="button" className="btn btn-primary" onClick={takeWork} disabled={!!claimingKey}>
              {claimingKey ? t("common.loading") : t("btn.assign")}
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={!!movePick.wo} onClose={closeMove} title={t("btn.move")}>
        <div className="space-y-3">
          <div className="text-xs text-slate-500">
            {movePick.wo ? orderReference(movePick.wo, `#${movePick.wo.production_order_id}`) : ""}
          </div>
          <div className="text-xs text-slate-500">
            {t("field.line")}: {flow.name} ({flow.code})
          </div>
          <div>
            <label className="label" htmlFor={`move-destination-${movePick.wo?.sewing_assignment_id || flowId}`}>
              {t("field.line")}
            </label>
            <select
              id={`move-destination-${movePick.wo?.sewing_assignment_id || flowId}`}
              className="input"
              value={movePick.destinationFlowId ?? ""}
              onChange={(event) => {
                const value = Number(event.target.value || 0);
                setMovePick((current) => ({ ...current, destinationFlowId: value > 0 ? value : null }));
              }}
            >
              <option value="">-</option>
              {destinationFlows.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name} ({candidate.code})
                </option>
              ))}
            </select>
          </div>
          {moveMsg && <div className="text-xs text-red-600">{moveMsg}</div>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn" onClick={closeMove}>{t("btn.cancel")}</button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={moveWork}
              disabled={!movePick.destinationFlowId || !!movingAssignmentId}
            >
              {movingAssignmentId ? t("common.loading") : t("btn.move")}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
