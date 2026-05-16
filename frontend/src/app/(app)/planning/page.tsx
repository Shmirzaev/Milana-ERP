"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function PlanningDashboard() {
  const { t } = useT();
  const { data: dash } = useSWR<any>("/api/dashboard/planning", fetcher);
  const { data: orders, mutate: mutateOrders } = useSWR<any[]>("/api/sales-orders?order_type=client_order&page_size=200", fetcher);
  const { data: models } = useSWR<any[]>("/api/models?status=approved", fetcher);
  const [brandedForm, setBrandedForm] = useState({ model_id: 0, planned_quantity: 100, size: "M", color: "white", deadline: "" });
  const [busyOrderId, setBusyOrderId] = useState<number | null>(null);

  const planningOrders = (orders || []).filter((o) => ["confirmed", "pending_sales_approval", "planning_approved"].includes(o.status));

  async function createPOForSO(soId: number) {
    setBusyOrderId(soId);
    try {
      const so = await api.get(`/api/sales-orders/${soId}`);
      const items = (so.items || []).map((i: any) => ({ model_id: i.model_id, color: i.color, size: i.size, planned_quantity: i.quantity }));
      const po = await api.post("/api/planning/create-production-order", {
        production_type: "client_order",
        sales_order_id: soId,
        model_id: so.items?.[0]?.model_id,
        planned_quantity: items.reduce((s: number, i: any) => s + i.planned_quantity, 0),
        // Carry the customer deadline through to the production order so the
        // process tracker shows a meaningful "due by" value.
        deadline: so.deadline ?? null,
        items,
      });
      // Cascade the deadline into each work-order (cutting/printing/sewing/packaging).
      if (so.deadline) {
        try { await api.post(`/api/production-orders/${po.id}/cascade-deadlines`); } catch {}
      }
      window.location.href = `/production-orders/${po.id}`;
    } finally {
      setBusyOrderId(null);
    }
  }

  async function sendEstimateToSales(soId: number) {
    setBusyOrderId(soId);
    try {
      await api.post(`/api/planning/submit-estimate/${soId}`);
      await mutateOrders();
    } finally {
      setBusyOrderId(null);
    }
  }

  async function createBranded(e: React.FormEvent) {
    e.preventDefault();
    const po = await api.post("/api/planning/create-branded-production", {
      production_type: "branded_stock",
      model_id: brandedForm.model_id,
      planned_quantity: brandedForm.planned_quantity,
      deadline: brandedForm.deadline || null,
      items: [{ model_id: brandedForm.model_id, color: brandedForm.color, size: brandedForm.size, planned_quantity: brandedForm.planned_quantity }],
    });
    if (brandedForm.deadline) {
      try { await api.post(`/api/production-orders/${po.id}/cascade-deadlines`); } catch {}
    }
    window.location.href = `/production-orders/${po.id}`;
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
                <td>{o.customer_id}</td>
                <td>${Number(o.total_amount).toFixed(2)}</td>
                <td>{o.status}</td>
                <td>
                  {o.status === "confirmed" && (
                    <button className="btn" disabled={busyOrderId === o.id} onClick={() => sendEstimateToSales(o.id)}>
                      {busyOrderId === o.id ? "Sending..." : "Send Estimate to Sales"}
                    </button>
                  )}
                  {o.status === "pending_sales_approval" && (
                    <button className="btn" disabled>
                      Waiting Sales Approval
                    </button>
                  )}
                  {o.status === "planning_approved" && (
                    <button className="btn btn-primary" disabled={busyOrderId === o.id} onClick={() => createPOForSO(o.id)}>
                      {busyOrderId === o.id ? "Creating..." : t("btn.createProductionOrder")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card p-4">
        <h2 className="font-medium mb-3">{t("page.planning.brandedSection")}</h2>
        <form onSubmit={createBranded} className="grid grid-cols-1 md:grid-cols-6 gap-3">
          <select className="input" value={brandedForm.model_id} onChange={(e) => setBrandedForm({ ...brandedForm, model_id: Number(e.target.value) })} required>
            <option value={0}>{t("ph.approvedModel")}</option>
            {models?.map((m) => <option key={m.id} value={m.id}>{m.code} — {m.name}</option>)}
          </select>
          <input className="input" placeholder={t("field.color")} value={brandedForm.color} onChange={(e) => setBrandedForm({ ...brandedForm, color: e.target.value })} />
          <input className="input" placeholder={t("field.size")} value={brandedForm.size} onChange={(e) => setBrandedForm({ ...brandedForm, size: e.target.value })} />
          <input className="input" type="number" value={brandedForm.planned_quantity} onChange={(e) => setBrandedForm({ ...brandedForm, planned_quantity: Number(e.target.value) })} />
          <input className="input" type="date" value={brandedForm.deadline} onChange={(e) => setBrandedForm({ ...brandedForm, deadline: e.target.value })} title={t("field.deadline")} />
          <button className="btn btn-primary">{t("btn.createBrandedPlan")}</button>
        </form>
      </div>
    </div>
  );
}
