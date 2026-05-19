"use client";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useState } from "react";
import { useT } from "@/lib/i18n";
import StagePipeline from "@/components/StagePipeline";

type PrintingAttachment = { file_url: string; file_name?: string | null; content_type?: string | null };

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
  const printFiles: PrintingAttachment[] = Array.isArray(so?.printing_attachments) ? so.printing_attachments : [];

  function isImageAttachment(a: PrintingAttachment): boolean {
    const byMime = (a.content_type || "").toLowerCase().startsWith("image/");
    const byName = /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(a.file_name || a.file_url || "");
    return byMime || byName;
  }

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
    setMsg(t("msg.planningApproved"));
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
            {so.status === "pending_sales_approval" && <button className="btn btn-primary" onClick={approvePlanning}>{t("btn.approvePlanningEstimate")}</button>}
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
            {so.planning_estimated_material_cost !== null && so.planning_estimated_material_cost !== undefined && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.soDetail.planningMaterialCost")}</dt><dd>${Number(so.planning_estimated_material_cost).toFixed(2)}</dd></div>
            )}
            {so.planning_estimated_labor_cost !== null && so.planning_estimated_labor_cost !== undefined && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.soDetail.planningLaborCost")}</dt><dd>${Number(so.planning_estimated_labor_cost).toFixed(2)}</dd></div>
            )}
            {so.planning_estimated_electricity_cost !== null && so.planning_estimated_electricity_cost !== undefined && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.soDetail.planningElectricityCost")}</dt><dd>${Number(so.planning_estimated_electricity_cost).toFixed(2)}</dd></div>
            )}
            {so.planning_estimated_other_cost !== null && so.planning_estimated_other_cost !== undefined && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.soDetail.planningOtherCost")}</dt><dd>${Number(so.planning_estimated_other_cost).toFixed(2)}</dd></div>
            )}
            {so.planning_estimated_net_cost !== null && so.planning_estimated_net_cost !== undefined && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.soDetail.planningNetPrice")}</dt><dd>${Number(so.planning_estimated_net_cost).toFixed(2)}</dd></div>
            )}
            {so.planning_suggested_price_15 !== null && so.planning_suggested_price_15 !== undefined && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.soDetail.priceWithProfit15")}</dt><dd>${Number(so.planning_suggested_price_15).toFixed(2)}</dd></div>
            )}
            {so.planning_suggested_price_20 !== null && so.planning_suggested_price_20 !== undefined && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.soDetail.priceWithProfit20")}</dt><dd>${Number(so.planning_suggested_price_20).toFixed(2)}</dd></div>
            )}
            {so.planning_estimated_lead_time_minutes !== null && so.planning_estimated_lead_time_minutes !== undefined && (
              <div className="flex justify-between"><dt className="text-slate-500">{t("page.soDetail.planningLeadTime")}</dt><dd>{(Number(so.planning_estimated_lead_time_minutes) / 60).toFixed(2)} h</dd></div>
            )}
            {so.planning_estimate_comment && (
              <div className="flex justify-between gap-3"><dt className="text-slate-500">{t("page.soDetail.planningComment")}</dt><dd className="text-right">{so.planning_estimate_comment}</dd></div>
            )}
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
          <h3 className="mb-2 font-medium">{t("page.soDetail.currentProductionStage")}</h3>
          <div className="mb-2 text-sm text-slate-600">
            {activeProcess.production_no} · {activeProcess.current_stage} · {activeProcess.current_stage_status || "in_progress"}
          </div>
          <StagePipeline currentStage={activeProcess.current_stage} stages={activeProcess.stages} compact={false} />
          {activeProcess.po_deadline && (
            <div className="mt-2 text-xs text-slate-500">
              {t("page.soDetail.etaDeadline")}: {new Date(activeProcess.po_deadline).toLocaleDateString()}
            </div>
          )}
        </div>
      )}

      {(so.printing_instructions || printFiles.length > 0) && (
        <div className="card mb-6 p-4">
          <h3 className="font-medium mb-2">Printing details</h3>
          {so.printing_instructions && (
            <div className="mb-3 rounded-md bg-[#f8f7f3] p-3 text-sm whitespace-pre-wrap">
              {so.printing_instructions}
            </div>
          )}
          {printFiles.length > 0 && (
            <div className="space-y-2">
              {printFiles.map((file, idx) => (
                <div key={`${file.file_url}-${idx}`} className="flex flex-wrap items-center gap-3 rounded-md border border-[#ecebe3] p-2">
                  {isImageAttachment(file) && <img src={file.file_url} alt={file.file_name || "print"} className="h-12 w-12 rounded object-cover" />}
                  <a className="text-sm text-[#3b3528] underline" href={file.file_url} target="_blank" rel="noreferrer">
                    {file.file_name || file.file_url}
                  </a>
                </div>
              ))}
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
