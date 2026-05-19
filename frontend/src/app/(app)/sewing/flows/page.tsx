"use client";
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";

type Flow = {
  id: number;
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
  production_order_id: number;
  operation: string;
  status: string;
  planned_input_qty: number;
  planned_output_qty: number;
  passed_qty: number;
  deadline: string | null;
  sewing_flow_id: number | null;
};

type Util = {
  committed_today: number;
  capacity_per_day: number;
  utilization_pct: number;
};

export default function SewingFlowsPage() {
  const { t } = useT();
  const { data: flows } = useSWR<Flow[]>("/api/sewing-flows", fetcher, { refreshInterval: 10_000 });
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  return (
    <div>
      <PageHeader title={t("page.sewingFlows.title")} subtitle={t("page.sewingFlows.subtitle")} />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {flows?.map((f) => {
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
                <div className="flex justify-between">
                  <dt className="text-slate-500">{t("page.sewingFlows.capacityPerDay")}</dt>
                  <dd>{f.capacity_per_day}</dd>
                </div>
              </dl>
              <div className="mb-2 h-2 w-full overflow-hidden rounded bg-slate-100" title={`${pctDone}% done`}>
                <div className="h-full bg-brand-500" style={{ width: `${pctDone}%` }} />
              </div>
              <FlowUtilization flowId={f.id} />
              <button
                type="button"
                className="btn w-full justify-center"
                onClick={() => setExpanded((prev) => ({ ...prev, [f.id]: !prev[f.id] }))}
              >
                {isExpanded
                  ? t("btn.cancel")
                  : (f.active_work_orders > 0 ? t("page.sewingFlows.assigned") : t("page.sewingFlows.readyForWork"))}
              </button>
              {isExpanded && <FlowDetail flowId={f.id} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FlowUtilization({ flowId }: { flowId: number }) {
  const { t } = useT();
  const { data } = useSWR<Util>(
    `/api/sewing-flows/${flowId}/utilization`,
    fetcher,
    { refreshInterval: 10_000 },
  );
  if (!data) return null;
  const pct = Math.min(100, data.utilization_pct);
  const color = pct < 70 ? "bg-green-500" : pct < 100 ? "bg-amber-500" : "bg-red-600";
  return (
    <div className="mb-2">
      <div className="mb-0.5 flex justify-between text-[10px] text-slate-500">
        <span>{t("page.sewingFlows.utilizationToday")}</span>
        <span>{data.committed_today}/{data.capacity_per_day} ({data.utilization_pct}%)</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded bg-slate-100">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function FlowDetail({ flowId }: { flowId: number }) {
  const { t } = useT();
  const { mutate: mutateGlobal } = useSWRConfig();
  const { data: wos, mutate: mutateAssigned } = useSWR<WO[]>(`/api/sewing-flows/${flowId}/work-orders?only_active=true`, fetcher);
  const { data: availableWos, mutate: mutateAvailableWos } = useSWR<WO[]>(
    "/api/work-orders?operation=sewing&only_active=true",
    fetcher,
  );
  const { data: util } = useSWR<Util>(`/api/sewing-flows/${flowId}/utilization`, fetcher, { refreshInterval: 10_000 });
  const [claimingId, setClaimingId] = useState<number | null>(null);
  const [loadingPickId, setLoadingPickId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [pick, setPick] = useState<{ wo: WO | null; qty: number; maxQty: number }>({ wo: null, qty: 0, maxQty: 0 });
  const showReadyPicker = !!wos && wos.length === 0;
  const freeCapacity = Math.max(0, (util?.capacity_per_day || 0) - (util?.committed_today || 0));

  async function openPick(wo: WO) {
    setLoadingPickId(wo.id);
    setMsg("");
    try {
      const assignments = await api.get<any[]>(`/api/work-orders/${wo.id}/assignments`);
      const assignedTotal = (assignments || []).reduce((sum, a) => sum + Number(a?.quantity || 0), 0);
      const planned = Number(wo.planned_input_qty || wo.planned_output_qty || 0);
      const remainingAssignable = Math.max(0, planned - assignedTotal);
      if (remainingAssignable <= 0) {
        setMsg(`${t("field.qty")} <= 0`);
        return;
      }
      const suggested = freeCapacity > 0 ? Math.min(remainingAssignable, freeCapacity) : remainingAssignable;
      setPick({ wo, qty: suggested > 0 ? suggested : 1, maxQty: remainingAssignable });
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setLoadingPickId(null);
    }
  }

  async function takeWork() {
    if (!pick.wo) return;
    const wid = pick.wo.id;
    const remainingWo = Math.max(0, Number(pick.maxQty || 0));
    const qty = Number(pick.qty || 0);
    if (util && freeCapacity <= 0) {
      setMsg(t("msg.lineFull"));
      return;
    }
    if (qty <= 0) {
      setMsg(t("field.qty") + " > 0");
      return;
    }
    if (remainingWo > 0 && qty > remainingWo) {
      setMsg(`${t("field.qty")} <= ${remainingWo}`);
      return;
    }
    if (freeCapacity > 0 && qty > freeCapacity) {
      setMsg(`${t("field.qty")} <= ${freeCapacity}`);
      return;
    }

    setMsg("");
    setClaimingId(wid);
    try {
      const now = new Date();
      const nextDay = new Date(now.getTime() + 24 * 60 * 60 * 1000);
      await api.post(`/api/work-orders/${wid}/assignments`, {
        work_order_id: wid,
        sewing_flow_id: flowId,
        quantity: qty,
        planned_start: now.toISOString(),
        planned_end: nextDay.toISOString(),
      });
      setPick({ wo: null, qty: 0, maxQty: 0 });
      await Promise.all([mutateAssigned(), mutateAvailableWos(), mutateGlobal("/api/sewing-flows")]);
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setClaimingId(null);
    }
  }

  if (!wos || !availableWos) return <div className="mt-3 text-xs text-slate-500">{t("common.loading")}</div>;

  return (
    <div className="mt-3 space-y-3">
      {wos.length > 0 ? (
        <div>
          <table className="table w-full table-fixed text-xs">
            <thead>
              <tr>
                <th className="w-[32%]">{t("field.productionNo")}</th>
                <th className="w-[22%]">{t("common.status")}</th>
                <th className="w-[24%]">{t("field.passed")}/{t("page.sewingFlows.plannedUnits")}</th>
                <th className="w-[22%]">{t("field.deadline2")}</th>
              </tr>
            </thead>
            <tbody>
              {wos.map((w) => (
                <tr key={w.id}>
                  <td className="truncate">
                    <Link href={`/production-orders/${w.production_order_id}`} className="text-brand-600 hover:underline">
                      PO #{w.production_order_id}
                    </Link>
                  </td>
                  <td><span className="badge">{statusLabel(w.status, t)}</span></td>
                  <td>{w.passed_qty} / {w.planned_output_qty}</td>
                  <td>{w.deadline ? new Date(w.deadline).toLocaleDateString() : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-xs text-slate-500">{t("page.sewingFlows.empty")}</div>
      )}

      {showReadyPicker && (
        <div className="rounded border border-slate-200 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{t("page.sewingFlows.assignableWork")}</div>
          {availableWos.length === 0 ? (
            <div className="text-xs text-slate-400">{t("page.sewingFlows.noUnassignedWork")}</div>
          ) : (
            <div>
              <table className="table w-full table-fixed text-xs">
                <thead>
                  <tr>
                    <th className="w-[27%]">{t("field.productionNo")}</th>
                    <th className="w-[18%]">{t("common.status")}</th>
                    <th className="w-[21%]">{t("field.passed")}/{t("page.sewingFlows.plannedUnits")}</th>
                    <th className="w-[16%]">{t("field.deadline2")}</th>
                    <th className="w-[18%] text-right">{t("field.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {availableWos.map((w) => (
                    <tr key={w.id}>
                      <td className="truncate">
                        <Link href={`/production-orders/${w.production_order_id}`} className="text-brand-600 hover:underline">
                          PO #{w.production_order_id}
                        </Link>
                      </td>
                      <td><span className="badge">{statusLabel(w.status, t)}</span></td>
                      <td>{w.passed_qty} / {w.planned_output_qty}</td>
                      <td>{w.deadline ? new Date(w.deadline).toLocaleDateString() : "-"}</td>
                      <td className="text-right">
                        <div className="flex flex-wrap justify-end gap-1">
                          <button className="btn h-7 px-2 text-[11px]" onClick={() => openPick(w)} disabled={claimingId === w.id || loadingPickId === w.id}>
                            {(claimingId === w.id || loadingPickId === w.id) ? t("common.loading") : t("btn.assign")}
                          </button>
                          <Link href={`/work-orders/${w.id}/sewing`} className="btn h-7 px-2 text-[11px]">{t("btn.open")}</Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {msg && <div className="mt-2 text-xs text-red-600">{msg}</div>}
        </div>
      )}

      <Modal open={!!pick.wo} onClose={() => setPick({ wo: null, qty: 0, maxQty: 0 })} title={t("btn.assign")}>
        <div className="space-y-3">
          <div className="text-xs text-slate-500">
            {pick.wo ? `PO #${pick.wo.production_order_id}` : ""}
          </div>
          <div className="text-xs text-slate-500">
            {t("field.passed")}/{t("page.sewingFlows.plannedUnits")}: {pick.wo ? `${pick.wo.passed_qty}/${pick.wo.planned_output_qty}` : "-"}
          </div>
          <div className="text-xs text-slate-500">
            {t("field.available")}: {pick.maxQty}
          </div>
          <div className="text-xs text-slate-500">
            {t("page.sewingFlows.capacityPerDay")}: {util?.capacity_per_day || 0}, {t("page.sewingFlows.utilizationToday")}: {util?.committed_today || 0}, {t("field.available")}: {freeCapacity}
          </div>
          <div>
            <label className="label">{t("field.qty")}</label>
            <input
              className="input"
              type="number"
              min={1}
              value={pick.qty}
              onChange={(e) => setPick((prev) => ({ ...prev, qty: Number(e.target.value) }))}
            />
          </div>
          {msg && <div className="text-xs text-red-600">{msg}</div>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn" onClick={() => setPick({ wo: null, qty: 0, maxQty: 0 })}>{t("btn.cancel")}</button>
            <button type="button" className="btn btn-primary" onClick={takeWork} disabled={!!claimingId}>
              {claimingId ? t("common.loading") : t("btn.assign")}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
