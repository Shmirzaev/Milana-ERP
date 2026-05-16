"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type EstimateFormState = {
  orderId: number;
  orderNo: string;
  materialCost: string;
  laborPercent: string;
  electricityPercent: string;
  otherPercent: string;
  leadHours: string;
  deadline: string;
  comment: string;
  materials: EstimateMaterialRow[];
};

type EstimateMaterialRow = {
  item_id: number;
  sku: string;
  name: string;
  category?: string | null;
  required_quantity: number;
  available_quantity: number;
  shortage: number;
  unit: string;
  unit_cost: number;
  estimated_cost: number;
};

const DEFAULT_LABOR_PERCENT = 12;
const DEFAULT_ELECTRICITY_PERCENT = 4;
const DEFAULT_OTHER_PERCENT = 3;

function num(v: string | number | null | undefined): number {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

export default function PlanningDashboard() {
  const { t } = useT();
  const { data: dash } = useSWR<any>("/api/dashboard/planning", fetcher);
  const { data: orders, mutate: mutateOrders } = useSWR<any[]>("/api/sales-orders?order_type=client_order&page_size=200", fetcher);
  const { data: models } = useSWR<any[]>("/api/models?status=approved", fetcher);
  const [brandedForm, setBrandedForm] = useState({ model_id: 0, planned_quantity: 100, size: "M", color: "white", deadline: "" });
  const [busyOrderId, setBusyOrderId] = useState<number | null>(null);
  const [estimateForm, setEstimateForm] = useState<EstimateFormState | null>(null);

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

  async function openEstimateDialog(soId: number) {
    setBusyOrderId(soId);
    try {
      const order = planningOrders.find((o) => o.id === soId);
      const estimate = await api.get(`/api/planning/estimate/${soId}`);
      const baseMaterialCost = num(estimate.estimated_material_cost);
      const savedLaborCost = num(estimate.estimated_labor_cost);
      const savedElectricityCost = num(estimate.estimated_electricity_cost);
      const savedOtherCost = num(estimate.estimated_other_expenses);
      const laborPercent = baseMaterialCost > 0 ? (savedLaborCost / baseMaterialCost) * 100 : DEFAULT_LABOR_PERCENT;
      const electricityPercent = baseMaterialCost > 0 ? (savedElectricityCost / baseMaterialCost) * 100 : DEFAULT_ELECTRICITY_PERCENT;
      const otherPercent = baseMaterialCost > 0 ? (savedOtherCost / baseMaterialCost) * 100 : DEFAULT_OTHER_PERCENT;
      setEstimateForm({
        orderId: soId,
        orderNo: order?.order_no || `#${soId}`,
        materialCost: baseMaterialCost.toFixed(2),
        laborPercent: round2(laborPercent).toFixed(2),
        electricityPercent: round2(electricityPercent).toFixed(2),
        otherPercent: round2(otherPercent).toFixed(2),
        leadHours: Number(estimate.estimated_lead_time_hours || 0).toFixed(2),
        deadline: order?.deadline ? String(order.deadline).slice(0, 10) : "",
        comment: "",
        materials: Array.isArray(estimate.materials) ? estimate.materials : [],
      });
    } finally {
      setBusyOrderId(null);
    }
  }

  async function submitEstimateToSales() {
    if (!estimateForm) return;
    const materialCost = Number(estimateForm.materialCost);
    const laborPercent = Number(estimateForm.laborPercent);
    const electricityPercent = Number(estimateForm.electricityPercent);
    const otherPercent = Number(estimateForm.otherPercent);
    const leadHours = Number(estimateForm.leadHours);
    if (!Number.isFinite(materialCost) || materialCost < 0) return;
    if (!Number.isFinite(laborPercent) || laborPercent < 0) return;
    if (!Number.isFinite(electricityPercent) || electricityPercent < 0) return;
    if (!Number.isFinite(otherPercent) || otherPercent < 0) return;
    if (!Number.isFinite(leadHours) || leadHours < 0) return;
    if (!estimateForm.deadline) return;
    const laborCost = round2(materialCost * laborPercent / 100);
    const electricityCost = round2(materialCost * electricityPercent / 100);
    const otherExpenses = round2(materialCost * otherPercent / 100);

    setBusyOrderId(estimateForm.orderId);
    try {
      await api.post(`/api/planning/submit-estimate/${estimateForm.orderId}`, {
        estimated_material_cost: materialCost,
        estimated_labor_cost: laborCost,
        estimated_electricity_cost: electricityCost,
        estimated_other_expenses: otherExpenses,
        estimated_lead_time_minutes: Math.round(leadHours * 60),
        planned_deadline: estimateForm.deadline,
        estimate_comment: estimateForm.comment.trim() || null,
      });
      setEstimateForm(null);
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
                    <button className="btn" disabled={busyOrderId === o.id} onClick={() => openEstimateDialog(o.id)}>
                      {busyOrderId === o.id ? "Loading..." : "Send Estimate to Sales"}
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

      {estimateForm && (
        <div className="fixed inset-0 z-40 bg-black/40 flex items-center justify-center p-4">
          <div className="card w-full max-w-4xl p-5 space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="text-lg font-semibold">Planning Estimate for {estimateForm.orderNo}</div>
            {(() => {
              const materialCost = num(estimateForm.materialCost);
              const laborPercent = num(estimateForm.laborPercent);
              const electricityPercent = num(estimateForm.electricityPercent);
              const otherPercent = num(estimateForm.otherPercent);
              const laborCost = round2(materialCost * laborPercent / 100);
              const electricityCost = round2(materialCost * electricityPercent / 100);
              const otherExpenses = round2(materialCost * otherPercent / 100);
              const netPrice = materialCost + laborCost + electricityCost + otherExpenses;
              const price15 = netPrice * 1.15;
              const price20 = netPrice * 1.20;
              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="label">Estimated Material Cost</label>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        step="0.01"
                        value={estimateForm.materialCost}
                        onChange={(e) => setEstimateForm({ ...estimateForm, materialCost: e.target.value })}
                      />
                    </div>
                    <div>
                      <label className="label">Estimated Lead Time (hours)</label>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        step="0.1"
                        value={estimateForm.leadHours}
                        onChange={(e) => setEstimateForm({ ...estimateForm, leadHours: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="text-xs text-slate-500">
                      Overhead is calculated as approximate percentages of total material/accessory cost.
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="card p-3">
                      <div className="text-xs text-slate-500 uppercase tracking-wide">Net Price</div>
                      <div className="text-lg font-semibold">${netPrice.toFixed(2)}</div>
                    </div>
                    <div className="card p-3">
                      <div className="text-xs text-slate-500 uppercase tracking-wide">Price (+15% Profit)</div>
                      <div className="text-lg font-semibold">${price15.toFixed(2)}</div>
                    </div>
                    <div className="card p-3">
                      <div className="text-xs text-slate-500 uppercase tracking-wide">Price (+20% Profit)</div>
                      <div className="text-lg font-semibold">${price20.toFixed(2)}</div>
                    </div>
                  </div>
                </div>
              );
            })()}
            {(() => {
              const allRows = estimateForm.materials || [];
              const materialRows = allRows.filter((m) => {
                const c = String(m.category || "").toLowerCase();
                return c === "fabric" || c === "semi_finished" || c === "";
              });
              const accessoryRows = allRows.filter((m) => {
                const c = String(m.category || "").toLowerCase();
                return c === "accessory" || c === "packaging";
              });
              const materialCost = num(estimateForm.materialCost);
              const laborPercent = num(estimateForm.laborPercent);
              const electricityPercent = num(estimateForm.electricityPercent);
              const otherPercent = num(estimateForm.otherPercent);
              const laborCost = round2(materialCost * laborPercent / 100);
              const electricityCost = round2(materialCost * electricityPercent / 100);
              const otherCost = round2(materialCost * otherPercent / 100);
              const renderEstimateRows = (rows: EstimateMaterialRow[]) => (
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Item</th>
                        <th>Usage</th>
                        <th>Unit Cost</th>
                        <th>Total Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.item_id}>
                          <td>
                            <div className="font-medium">{row.name}</div>
                            <div className="text-xs text-slate-500">{row.sku}</div>
                          </td>
                          <td>{Number(row.required_quantity || 0).toFixed(2)} {row.unit}</td>
                          <td>${Number(row.unit_cost || 0).toFixed(2)}</td>
                          <td>${Number(row.estimated_cost || 0).toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );

              return (
                <div className="space-y-4">
                  <div>
                    <div className="text-sm font-semibold mb-2">Material Usage and Cost</div>
                    {materialRows.length > 0 ? renderEstimateRows(materialRows) : <div className="text-sm text-slate-500">No material rows from model BOM.</div>}
                  </div>
                  <div>
                    <div className="text-sm font-semibold mb-2">Accessories Usage and Cost</div>
                    {accessoryRows.length > 0 ? renderEstimateRows(accessoryRows) : <div className="text-sm text-slate-500">No accessory rows from model BOM.</div>}
                  </div>
                  <div>
                    <div className="text-sm font-semibold mb-2">Other Expenses (Approx.)</div>
                    <div className="overflow-x-auto">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Expense</th>
                            <th>Approx. %</th>
                            <th>Base Cost</th>
                            <th>Approx. Cost</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td>Labor</td>
                            <td>
                              <input
                                className="input"
                                type="number"
                                min={0}
                                step="0.1"
                                value={estimateForm.laborPercent}
                                onChange={(e) => setEstimateForm({ ...estimateForm, laborPercent: e.target.value })}
                              />
                            </td>
                            <td>${materialCost.toFixed(2)}</td>
                            <td>${laborCost.toFixed(2)}</td>
                          </tr>
                          <tr>
                            <td>Electricity</td>
                            <td>
                              <input
                                className="input"
                                type="number"
                                min={0}
                                step="0.1"
                                value={estimateForm.electricityPercent}
                                onChange={(e) => setEstimateForm({ ...estimateForm, electricityPercent: e.target.value })}
                              />
                            </td>
                            <td>${materialCost.toFixed(2)}</td>
                            <td>${electricityCost.toFixed(2)}</td>
                          </tr>
                          <tr>
                            <td>Other Expenses</td>
                            <td>
                              <input
                                className="input"
                                type="number"
                                min={0}
                                step="0.1"
                                value={estimateForm.otherPercent}
                                onChange={(e) => setEstimateForm({ ...estimateForm, otherPercent: e.target.value })}
                              />
                            </td>
                            <td>${materialCost.toFixed(2)}</td>
                            <td>${otherCost.toFixed(2)}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              );
            })()}
            <div>
              <label className="label">Planning Deadline</label>
              <input
                className="input"
                type="date"
                value={estimateForm.deadline}
                onChange={(e) => setEstimateForm({ ...estimateForm, deadline: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="label">Planning Comment</label>
              <textarea
                className="input min-h-24"
                placeholder="Optional comment for Sales approval"
                value={estimateForm.comment}
                onChange={(e) => setEstimateForm({ ...estimateForm, comment: e.target.value })}
              />
            </div>
            <div className="flex justify-end gap-2">
              <button className="btn" onClick={() => setEstimateForm(null)} disabled={busyOrderId === estimateForm.orderId}>Cancel</button>
              <button className="btn btn-primary" onClick={submitEstimateToSales} disabled={busyOrderId === estimateForm.orderId || !estimateForm.deadline}>
                {busyOrderId === estimateForm.orderId ? "Sending..." : "Send to Sales"}
              </button>
            </div>
          </div>
        </div>
      )}

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
