"use client";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useState } from "react";
import { useT } from "@/lib/i18n";
import StagePipeline from "@/components/StagePipeline";

export default function SalesOrderDetail() {
  const params = useParams<{ id: string }>();
  const { t } = useT();
  const id = params.id;
  const { data: so, mutate } = useSWR<any>(`/api/sales-orders/${id}`, fetcher);
  const { data: mr } = useSWR<any[]>(so ? `/api/planning/material-requirements/${id}` : null, fetcher);
  const { data: processes } = useSWR<any[]>(so ? "/api/process-tracking" : null, fetcher);
  const [msg, setMsg] = useState("");
  const linkedProcesses = (processes || []).filter((p) => String(p.sales_order_id) === String(id));
  const activeProcess = linkedProcesses.find((p) => p.current_stage !== "completed") || linkedProcesses[0];

  async function confirm() {
    await api.post(`/api/sales-orders/${id}/confirm`);
    mutate();
  }
  async function reserveStock() {
    const r = await api.post(`/api/sales-orders/${id}/reserve-stock`);
    setMsg(t("page.soDetail.reservationsLine", { res: r.reservations.length, sh: r.shortages.length }));
    mutate();
  }
  async function approvePlanning() {
    await api.post(`/api/sales-orders/${id}/approve-planning`);
    setMsg("Planning estimate approved and sent back to Planning for PO creation.");
    mutate();
  }

  if (!so) return <div>{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader
        title={t("page.soDetail.title", { orderNo: so.order_no })}
        subtitle={t("page.soDetail.subtitle", { type: so.order_type === "client_order" ? t("orderType.client") : t("orderType.branded"), status: so.status })}
        actions={
          <div className="flex gap-2">
            {so.status === "draft" && <button className="btn btn-primary" onClick={confirm}>{t("btn.confirm")}</button>}
            {so.status === "pending_sales_approval" && <button className="btn btn-primary" onClick={approvePlanning}>Approve Planning Estimate</button>}
            {so.order_type === "branded_stock_sale" && <button className="btn" onClick={reserveStock}>{t("btn.reserveStock")}</button>}
          </div>
        }
      />
      {msg && <div className="card p-3 mb-4 text-sm">{msg}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="card p-4">
          <h3 className="font-medium mb-2">{t("page.soDetail.details")}</h3>
          <dl className="text-sm space-y-1">
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.orderNo")}</dt><dd>{so.order_no}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.customer")}</dt><dd>{so.customer_id || "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.total")}</dt><dd>${Number(so.total_amount).toFixed(2)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.deadline")}</dt><dd>{so.deadline ? new Date(so.deadline).toLocaleDateString() : "—"}</dd></div>
          </dl>
        </div>
        <div className="card p-4">
          <h3 className="font-medium mb-2">{t("page.soDetail.items")}</h3>
          <table className="table">
            <thead><tr><th>{t("field.model")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th><th>{t("field.qty")}</th><th>{t("field.price")}</th></tr></thead>
            <tbody>
              {so.items?.map((i: any) => (
                <tr key={i.id}><td>{i.model_id}</td><td>{i.color}</td><td>{i.size}</td><td>{i.quantity}</td><td>${Number(i.unit_price).toFixed(2)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {activeProcess && (
        <div className="card mb-6 p-4">
          <h3 className="mb-2 font-medium">Current Production Stage</h3>
          <div className="mb-2 text-sm text-slate-600">
            {activeProcess.production_no} · {activeProcess.current_stage} · {activeProcess.current_stage_status || "in_progress"}
          </div>
          <StagePipeline currentStage={activeProcess.current_stage} stages={activeProcess.stages} compact={false} />
          {activeProcess.po_deadline && (
            <div className="mt-2 text-xs text-slate-500">
              ETA / deadline: {new Date(activeProcess.po_deadline).toLocaleDateString()}
            </div>
          )}
        </div>
      )}

      <div className="card p-4">
        <h3 className="font-medium mb-2">{t("page.soDetail.materialReq")}</h3>
        <table className="table">
          <thead><tr><th>{t("field.item")}</th><th>{t("field.required")}</th><th>{t("field.available")}</th><th>{t("field.shortage")}</th></tr></thead>
          <tbody>
            {mr?.map((m, i) => (
              <tr key={i}><td>{m.sku} — {m.name}</td><td>{m.required_quantity.toFixed(2)} {m.unit}</td><td>{m.available_quantity.toFixed(2)}</td><td className={m.shortage > 0 ? "text-red-600" : ""}>{m.shortage.toFixed(2)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
