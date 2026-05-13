"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";
import { useMe, can } from "@/lib/auth";

type WO = {
  id: number;
  operation: string;
  department_id: number;
  status: string;
  actual_input_qty: number;
  actual_output_qty: number;
  passed_qty: number;
  failed_qty: number;
  deadline: string | null;
  assigned_to: number | null;
  sewing_flow_id: number | null;
};

export default function ProductionOrderDetail() {
  const params = useParams<{ id: string }>();
  const { t } = useT();
  const { me } = useMe();
  const canPlan = can(me, "*", "planning.production");
  const id = params.id;
  const { data: po, mutate } = useSWR<any>(`/api/production-orders/${id}`, fetcher);
  const { data: flows } = useSWR<any[]>("/api/sewing-flows", fetcher);
  const { data: users } = useSWR<any[]>(canPlan ? "/api/users" : null, fetcher);

  const [editing, setEditing] = useState<WO | null>(null);
  const [edit, setEdit] = useState({ deadline: "", sewing_flow_id: 0, assigned_to: 0 });
  const [editMsg, setEditMsg] = useState("");

  async function createWOs() {
    await api.post(`/api/production-orders/${id}/create-work-orders?include_printing=false`);
    mutate();
  }
  async function startWO(wid: number) { await api.post(`/api/work-orders/${wid}/start`); mutate(); }
  async function completeWO(wid: number) { await api.post(`/api/work-orders/${wid}/complete`); mutate(); }

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

  if (!po) return <div>{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader
        title={t("page.poDetail.title", { productionNo: po.production_no })}
        subtitle={t("page.poDetail.subtitle", { type: po.production_type, status: po.status })}
        actions={canPlan ? <button className="btn" onClick={createWOs}>{t("btn.generateWorkOrders")}</button> : undefined}
      />

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
          <h3 className="font-medium mb-2">{t("page.poDetail.summary")}</h3>
          <dl className="text-sm space-y-1">
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.model")}</dt><dd>{po.model_id}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.poDetail.salesOrder")}</dt><dd>{po.sales_order_id || "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.poDetail.plannedQty")}</dt><dd>{po.planned_quantity}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.deadline")}</dt><dd>{po.deadline ? new Date(po.deadline).toLocaleDateString() : "—"}</dd></div>
          </dl>
        </div>
      </div>

      <div className="card p-4">
        <h3 className="font-medium mb-2">{t("page.poDetail.workOrders")}</h3>
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>{t("page.poDetail.op")}</th>
                <th>{t("common.status")}</th>
                <th>{t("field.input")}</th>
                <th>{t("field.output")}</th>
                <th>{t("field.passed")}</th>
                <th>{t("field.failed")}</th>
                <th>{t("field.deadline2")}</th>
                <th>{t("field.line")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {po.work_orders?.map((w: WO) => (
                <tr key={w.id}>
                  <td className="font-medium">{w.operation}</td>
                  <td><span className="badge">{w.status}</span></td>
                  <td>{w.actual_input_qty}</td>
                  <td>{w.actual_output_qty}</td>
                  <td>{w.passed_qty}</td>
                  <td>{w.failed_qty}</td>
                  <td>{w.deadline ? new Date(w.deadline).toLocaleDateString() : "—"}</td>
                  <td>{flows?.find((f) => f.id === w.sewing_flow_id)?.code ?? "—"}</td>
                  <td className="flex gap-2 flex-wrap">
                    {w.status === "waiting" && <button className="text-brand-600 hover:underline" onClick={() => startWO(w.id)}>{t("btn.start")}</button>}
                    {w.status === "in_progress" && <button className="text-green-700 hover:underline" onClick={() => completeWO(w.id)}>{t("btn.complete")}</button>}
                    {canPlan && (
                      <button className="text-slate-700 hover:underline" onClick={() => openEdit(w)}>{t("btn.assign")}</button>
                    )}
                    {w.operation === "cutting" && <Link href={`/work-orders/${w.id}/cutting`} className="text-brand-600 hover:underline">{t("dash.cutting")}</Link>}
                    {w.operation === "printing" && <Link href={`/work-orders/${w.id}/printing`} className="text-brand-600 hover:underline">{t("dash.printing")}</Link>}
                    {w.operation === "sewing" && <Link href={`/work-orders/${w.id}/sewing`} className="text-brand-600 hover:underline">{t("dash.sewing")}</Link>}
                    {w.operation === "packaging" && <Link href={`/work-orders/${w.id}/packaging`} className="text-brand-600 hover:underline">{t("dash.packaging")}</Link>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing ? `${editing.operation.toUpperCase()} #${editing.id}` : ""}>
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
                {flows?.map((f) => <option key={f.id} value={f.id}>{f.code} — {f.name}</option>)}
              </select>
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
