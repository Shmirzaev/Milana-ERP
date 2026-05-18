"use client";
import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

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
};

export default function SewingFlowsPage() {
  const { t } = useT();
  const { data: flows } = useSWR<Flow[]>("/api/sewing-flows", fetcher);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  return (
    <div>
      <PageHeader title={t("page.sewingFlows.title")} subtitle={t("page.sewingFlows.subtitle")} />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {flows?.map((f) => {
          const isExpanded = !!expanded[f.id];
          const pctDone = f.planned_units > 0 ? Math.min(100, Math.round(100 * f.completed_units / f.planned_units)) : 0;
          return (
          <div key={f.id} className="card p-4">
            <div className="flex items-start justify-between mb-2">
              <div>
                <div className="text-lg font-semibold text-slate-900">{f.name}</div>
                <div className="text-xs text-slate-500"><code>{f.code}</code></div>
              </div>
              <span className={`badge ${f.is_active ? "badge-green" : "badge-red"}`}>
                {f.is_active ? t("field.active") : t("field.inactive")}
              </span>
            </div>
            <dl className="text-sm space-y-1 mb-3">
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
            {/* Progress: done / planned */}
            <div className="w-full h-2 bg-slate-100 rounded overflow-hidden mb-2" title={`${pctDone}% done`}>
              <div className="h-full bg-brand-500" style={{ width: `${pctDone}%` }} />
            </div>
            <FlowUtilization flowId={f.id} />
            <button
              type="button"
              className="btn w-full justify-center"
              onClick={() => setExpanded((prev) => ({ ...prev, [f.id]: !prev[f.id] }))}
            >
              {isExpanded ? t("btn.cancel") : t("page.sewingFlows.assigned")}
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
  const { data } = useSWR<{ committed_today: number; capacity_per_day: number; utilization_pct: number }>(
    `/api/sewing-flows/${flowId}/utilization`,
    fetcher,
    { refreshInterval: 60_000 },
  );
  if (!data) return null;
  const pct = Math.min(100, data.utilization_pct);
  const color = pct < 70 ? "bg-green-500" : pct < 100 ? "bg-amber-500" : "bg-red-600";
  return (
    <div className="mb-2">
      <div className="flex justify-between text-[10px] text-slate-500 mb-0.5">
        <span>Utilization today</span>
        <span>{data.committed_today}/{data.capacity_per_day} ({data.utilization_pct}%)</span>
      </div>
      <div className="w-full h-1.5 bg-slate-100 rounded overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function FlowDetail({ flowId }: { flowId: number }) {
  const { t } = useT();
  const { data: wos } = useSWR<WO[]>(`/api/sewing-flows/${flowId}/work-orders?only_active=true`, fetcher);
  if (!wos) return <div className="text-xs text-slate-500 mt-3">{t("common.loading")}</div>;
  if (!wos.length) return <div className="text-xs text-slate-500 mt-3">{t("page.sewingFlows.empty")}</div>;
  return (
    <table className="table mt-3 text-xs">
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
            <td><span className="badge">{w.status}</span></td>
            <td>{w.passed_qty} / {w.planned_output_qty}</td>
            <td>{w.deadline ? new Date(w.deadline).toLocaleDateString() : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
