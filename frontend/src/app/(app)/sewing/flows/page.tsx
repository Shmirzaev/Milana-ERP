"use client";
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
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
  planned_output_qty: number;
  passed_qty: number;
  deadline: string | null;
  sewing_flow_id: number | null;
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
  const { data } = useSWR<{ committed_today: number; capacity_per_day: number; utilization_pct: number }>(
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
  const { data: unassigned, mutate: mutateUnassigned } = useSWR<WO[]>(
    "/api/work-orders?operation=sewing&only_active=true&unassigned_flow=true",
    fetcher,
  );
  const [claimingId, setClaimingId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const showReadyPicker = !!wos && wos.length === 0;

  async function takeWork(wid: number) {
    setMsg("");
    setClaimingId(wid);
    try {
      await api.patch(`/api/work-orders/${wid}`, { sewing_flow_id: flowId });
      await Promise.all([mutateAssigned(), mutateUnassigned(), mutateGlobal("/api/sewing-flows")]);
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setClaimingId(null);
    }
  }

  if (!wos || !unassigned) return <div className="mt-3 text-xs text-slate-500">{t("common.loading")}</div>;

  return (
    <div className="mt-3 space-y-3">
      {wos.length > 0 ? (
        <table className="table text-xs">
          <thead>
            <tr>
              <th>{t("field.productionNo")}</th>
              <th>{t("common.status")}</th>
              <th>{t("field.passed")}/{t("page.sewingFlows.plannedUnits")}</th>
              <th>{t("field.deadline2")}</th>
            </tr>
          </thead>
          <tbody>
            {wos.map((w) => (
              <tr key={w.id}>
                <td>
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
      ) : (
        <div className="text-xs text-slate-500">{t("page.sewingFlows.empty")}</div>
      )}

      {showReadyPicker && (
        <div className="rounded border border-slate-200 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{t("page.sewingFlows.unassignedWork")}</div>
          {unassigned.length === 0 ? (
            <div className="text-xs text-slate-400">{t("page.sewingFlows.noUnassignedWork")}</div>
          ) : (
            <table className="table text-xs">
              <thead>
                <tr>
                  <th>{t("field.productionNo")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("field.passed")}/{t("page.sewingFlows.plannedUnits")}</th>
                  <th>{t("field.deadline2")}</th>
                  <th>{t("field.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {unassigned.map((w) => (
                  <tr key={w.id}>
                    <td>
                      <Link href={`/production-orders/${w.production_order_id}`} className="text-brand-600 hover:underline">
                        PO #{w.production_order_id}
                      </Link>
                    </td>
                    <td><span className="badge">{statusLabel(w.status, t)}</span></td>
                    <td>{w.passed_qty} / {w.planned_output_qty}</td>
                    <td>{w.deadline ? new Date(w.deadline).toLocaleDateString() : "-"}</td>
                    <td className="flex gap-2">
                      <button className="btn" onClick={() => takeWork(w.id)} disabled={claimingId === w.id}>
                        {claimingId === w.id ? t("common.loading") : t("btn.assign")}
                      </button>
                      <Link href={`/work-orders/${w.id}/sewing`} className="btn">{t("btn.open")}</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {msg && <div className="mt-2 text-xs text-red-600">{msg}</div>}
        </div>
      )}
    </div>
  );
}
