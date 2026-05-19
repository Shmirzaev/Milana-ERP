"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import StagePipeline, { operationLabel, statusLabel } from "@/components/StagePipeline";

type Stage = {
  work_order_id: number;
  operation: string;
  status: string;
  planned: number;
  completed: number;
  failed: number;
  rework: number;
  progress_pct: number;
  assigned_to: number | null;
  sewing_flow_id: number | null;
  sewing_flow_code: string | null;
  sewing_flow_name: string | null;
  deadline: string | null;
  overdue: boolean;
};

type Process = {
  production_order_id: number;
  production_no: string;
  production_type: string;
  po_status: string;
  po_deadline: string | null;
  po_overdue: boolean;
  planned_quantity: number;
  sales_order_id: number | null;
  sales_order_no: string | null;
  customer_name: string | null;
  model_code: string | null;
  model_name: string | null;
  is_blocked?: boolean;
  blocked_by?: { work_order_id: number; operation: string; reason: string | null } | null;
  current_stage: string;
  current_stage_status: string | null;
  current_sewing_flow: string | null;
  stages: Stage[];
};

const STAGE_COLORS: Record<string, string> = {
  cutting: "bg-rose-100 text-rose-800",
  printing: "bg-fuchsia-100 text-fuchsia-800",
  sewing: "bg-orange-100 text-orange-800",
  packaging: "bg-emerald-100 text-emerald-800",
  storage_transfer: "bg-cyan-100 text-cyan-800",
  planning_required: "bg-amber-100 text-amber-800",
  completed: "bg-slate-200 text-slate-700",
};

export default function ProcessTrackingPage() {
  const { t } = useT();
  const { data, error, isLoading, mutate } = useSWR<Process[]>(
    "/api/process-tracking",
    fetcher,
    { refreshInterval: 10_000 },
  );

  function openPdf() {
    api.openLabel("/api/process-tracking/export");
  }
  const [filter, setFilter] = useState<string>("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const filtered = useMemo(() => {
    if (!data) return [];
    if (!filter) return data;
    const q = filter.toLowerCase();
    return data.filter((p) =>
      p.production_no?.toLowerCase().includes(q) ||
      (p.sales_order_no || "").toLowerCase().includes(q) ||
      (p.customer_name || "").toLowerCase().includes(q) ||
      (p.model_code || "").toLowerCase().includes(q) ||
      p.current_stage.toLowerCase().includes(q)
    );
  }, [data, filter]);

  const overdue = (data || []).filter((p) => p.po_overdue || p.stages.some((s) => s.overdue)).length;

  return (
    <div>
      <PageHeader
        title={t("page.processes.title")}
        subtitle={t("page.processes.subtitle")}
        actions={
          <div className="flex gap-2">
            <button className="btn" onClick={() => mutate()} title={t("page.processes.refresh")}>↻</button>
            <button className="btn" onClick={openPdf}>{t("page.processes.exportPdf")}</button>
          </div>
        }
      />

      {error && (
        <div className="card p-3 mb-4 text-sm text-red-700 bg-red-50 border-red-200">
          {String((error as any).message ?? error)}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="card p-4">
          <div className="text-xs text-slate-500 uppercase">{t("page.processes.allActive")}</div>
          <div className="text-2xl font-semibold">{data?.length ?? 0}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-slate-500 uppercase">{t("page.processes.overdue")}</div>
          <div className="text-2xl font-semibold text-red-600">{overdue}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-slate-500 uppercase">{t("common.search")}</div>
          <input
            className="input mt-1"
            placeholder={t("page.processes.searchPlaceholder")}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      </div>

      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.productionNo")}</th>
              <th>{t("field.customer")}</th>
              <th>{t("field.model")}</th>
              <th>{t("field.qty")}</th>
              <th>{t("page.processes.currentStage")}</th>
              <th>{t("page.processes.assignedFlow")}</th>
              <th>{t("page.processes.deadline")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={8} className="text-slate-500">{t("common.loading")}</td></tr>
            )}
            {!isLoading && filtered.length === 0 && (
              <tr><td colSpan={8} className="text-slate-500">{t("page.processes.empty")}</td></tr>
            )}
            {filtered.map((p) => (
              <>
                <tr key={p.production_order_id}>
                  <td>
                    <div className="font-medium">
                      <Link href={`/production-orders/${p.production_order_id}`} className="text-brand-600 hover:underline">
                        {p.production_no}
                      </Link>
                    </div>
                    {p.sales_order_no && (
                      <div className="text-xs text-slate-500">
                        <Link href={`/sales-orders/${p.sales_order_id}`} className="hover:underline">
                          {p.sales_order_no}
                        </Link>
                      </div>
                    )}
                  </td>
                  <td>{p.customer_name || "—"}</td>
                  <td>
                    <div className="font-medium text-sm">{p.model_code}</div>
                    <div className="text-xs text-slate-500">{p.model_name}</div>
                  </td>
                  <td>{p.planned_quantity}</td>
                  <td>
                    <StagePipeline currentStage={p.current_stage} stages={p.stages} compact={false} />
                    <div className="mt-1">
                      <span className={`badge ${STAGE_COLORS[p.current_stage] || "badge"}`}>{operationLabel(p.current_stage, t)}</span>
                    </div>
                    {p.current_stage_status && (
                      <div className="text-xs text-slate-500 mt-1">{statusLabel(p.current_stage_status, t)}</div>
                    )}
                    {p.is_blocked && p.blocked_by && (
                      <div className="text-xs text-red-700 mt-1" title={p.blocked_by.reason ?? ""}>
                        ⛔ {t("page.processes.blockedOn", { operation: operationLabel(p.blocked_by.operation, t) })}
                      </div>
                    )}
                  </td>
                  <td>{p.current_sewing_flow || "—"}</td>
                  <td className={p.po_overdue ? "text-red-600 font-medium" : ""}>
                    {p.po_deadline ? new Date(p.po_deadline).toLocaleDateString() : "—"}
                  </td>
                  <td className="flex flex-col gap-1">
                    <button
                      onClick={() => setExpanded(expanded === p.production_order_id ? null : p.production_order_id)}
                      className="text-brand-600 hover:underline text-left"
                    >
                      {expanded === p.production_order_id ? t("btn.cancel") : t("btn.view")}
                    </button>
                    <Link
                      href={`/admin/audit-logs?entity=ProductionOrder&id=${p.production_order_id}`}
                      className="text-xs text-slate-500 hover:underline"
                    >
                      {t("page.processes.audit")}
                    </Link>
                  </td>
                </tr>
                {expanded === p.production_order_id && (
                  <tr key={`${p.production_order_id}-detail`}>
                    <td colSpan={8} className="bg-slate-50 p-3">
                      <div className="text-xs font-medium text-slate-500 uppercase mb-2">
                        {t("page.processes.stagesHeader")}
                      </div>
                      <table className="table text-xs">
                        <thead>
                          <tr>
                            <th>{t("field.operation")}</th>
                            <th>{t("common.status")}</th>
                            <th>{t("page.processes.progress")}</th>
                            <th>{t("field.passed")} / {t("field.failed")}</th>
                            <th>{t("page.processes.assignedFlow")}</th>
                            <th>{t("page.processes.deadline")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {p.stages.map((s) => (
                            <tr key={s.work_order_id}>
                              <td>
                                <span className={`badge ${STAGE_COLORS[s.operation] || "badge"}`}>{operationLabel(s.operation, t)}</span>
                              </td>
                              <td>{statusLabel(s.status, t)}</td>
                              <td>
                                <div className="w-32 h-2 bg-slate-200 rounded overflow-hidden">
                                  <div
                                    className="h-full bg-brand-500"
                                    style={{ width: `${Math.min(100, s.progress_pct)}%` }}
                                  />
                                </div>
                                <div className="text-[10px] text-slate-500 mt-0.5">{s.completed}/{s.planned} ({s.progress_pct}%)</div>
                              </td>
                              <td>{s.completed} / {s.failed}</td>
                              <td>{s.sewing_flow_code || "—"}</td>
                              <td className={s.overdue ? "text-red-600" : ""}>
                                {s.deadline ? new Date(s.deadline).toLocaleDateString() : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
