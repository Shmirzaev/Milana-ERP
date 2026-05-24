"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel } from "@/lib/batchSerial";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { operationLabel, productionTypeLabel, statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { useMe, can } from "@/lib/auth";

type WO = {
  id: number;
  production_batch_id?: number | null;
  operation: string;
  department_id: number;
  status: string;
  planned_input_qty: number;
  actual_input_qty: number;
  actual_output_qty: number;
  passed_qty: number;
  failed_qty: number;
  deadline: string | null;
  assigned_to: number | null;
  sewing_flow_id: number | null;
  is_blocked: boolean;
  block_reason: string | null;
};

type BatchMeta = {
  id: number;
  batch_no: string;
  batch_index: number;
  name: string | null;
  planned_quantity: number;
};

type Assignment = {
  id: number;
  work_order_id: number;
  sewing_flow_id: number;
  quantity: number;
  completed_qty: number;
  planned_start: string | null;
  planned_end: string | null;
  status: string;
  notes: string | null;
};

type Flow = {
  id: number;
  code: string;
  name: string;
};

type FlowUtil = {
  flow_id: number;
  committed_today: number;
  capacity_per_day: number;
  utilization_pct: number;
  is_full: boolean;
};

export default function ProductionOrderDetail() {
  const params = useParams<{ id: string }>();
  const { t } = useT();
  const { me } = useMe();
  const canPlan = can(me, "*", "planning.production");
  const isAdmin = can(me, "*");
  const id = params.id;
  const isNumericId = /^\d+$/.test(String(id || ""));
  const { data: po, error: poError, isLoading: poLoading, mutate } = useSWR<any>(isNumericId ? `/api/production-orders/${id}` : null, fetcher);
  const { data: flows } = useSWR<Flow[]>("/api/sewing-flows", fetcher);
  const { data: flowUtil } = useSWR<FlowUtil[]>("/api/sewing-flows/utilization-snapshot", fetcher, { refreshInterval: 60_000 });
  const { data: users } = useSWR<any[]>(canPlan ? "/api/users" : null, fetcher);
  const utilByFlow = new Map((flowUtil || []).map((u) => [u.flow_id, u]));
  const batchById = new Map<number, BatchMeta>(((po?.batches || []) as BatchMeta[]).map((b) => [b.id, b]));

  const [editing, setEditing] = useState<WO | null>(null);
  const [edit, setEdit] = useState({ deadline: "", sewing_flow_id: 0, assigned_to: 0 });
  const [editMsg, setEditMsg] = useState("");
  const [openAssignments, setOpenAssignments] = useState<number | null>(null);
  const [repairing, setRepairing] = useState(false);
  const [repairMsg, setRepairMsg] = useState("");

  async function cascade() {
    try { await api.post(`/api/production-orders/${id}/cascade-deadlines`); mutate(); }
    catch (e: any) { alert(e.message); }
  }
  async function blockWO(wid: number) {
    const reason = prompt(t("page.poDetail.blockReasonPrompt"));
    if (!reason) return;
    try { await api.post(`/api/work-orders/${wid}/block`, { reason }); mutate(); }
    catch (e: any) { alert(e.message); }
  }
  async function unblockWO(wid: number) {
    try { await api.post(`/api/work-orders/${wid}/unblock`); mutate(); }
    catch (e: any) { alert(e.message); }
  }

  async function repairTotals() {
    if (!confirm(t("page.poDetail.confirmRepairTotals"))) return;
    setRepairing(true);
    setRepairMsg("");
    try {
      const r = await api.post(`/api/production-orders/${id}/admin-repair-totals`);
      setRepairMsg(t("page.poDetail.repairFinished", { count: Number(r?.changed_count || 0) }));
      mutate();
    } catch (e: any) {
      setRepairMsg(e.message || t("page.poDetail.repairFailed"));
    } finally {
      setRepairing(false);
    }
  }

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

  if (!isNumericId) {
    return (
      <div className="card p-4 text-sm text-red-700">
        Could not load production order. The detail URL must use the numeric production order ID.
      </div>
    );
  }
  if (poError) {
    return (
      <div className="card p-4 text-sm text-red-700">
        <div>Could not load production order. Please try again.</div>
        <button className="btn mt-3" onClick={() => mutate()}>Retry</button>
      </div>
    );
  }
  if (poLoading || !po) return <div className="card p-4 text-sm text-slate-500">{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader
        title={t("page.poDetail.title", { productionNo: po.production_no })}
        subtitle={t("page.poDetail.subtitle", { type: productionTypeLabel(po.production_type, t), status: statusLabel(po.status, t) })}
        actions={canPlan ? (
          <div className="flex gap-2">
            <button className="btn" onClick={cascade} title={t("page.poDetail.cascadeDeadlinesHint")}>{t("page.poDetail.cascadeDeadlines")}</button>
            {isAdmin && (
              <button className="btn" onClick={repairTotals} disabled={repairing} title={t("page.poDetail.repairTotalsHint")}>
                {repairing ? t("page.poDetail.repairing") : t("page.poDetail.repairTotals")}
              </button>
            )}
          </div>
        ) : undefined}
      />
      {repairMsg && <div className="mb-3 text-sm text-slate-600">{repairMsg}</div>}

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
                <th>{t("field.batch")}</th>
                <th>{t("page.poDetail.op")}</th>
                <th>{t("common.status")}</th>
                <th>{t("field.input")}</th>
                <th>{t("field.output")}</th>
                <th>{t("field.failed")}</th>
                <th>{t("field.deadline2")}</th>
                <th>{t("field.line")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {po.work_orders?.map((w: WO) => (
                <>
                  <tr key={w.id} className={w.is_blocked ? "bg-red-50" : ""}>
                    <td>
                      {w.production_batch_id
                        ? (() => {
                            const b = batchById.get(w.production_batch_id);
                            return b ? formatBatchLabel(b, po?.id) : "-";
                          })()
                        : "-"}
                    </td>
                    <td className="font-medium">
                      {operationLabel(w.operation, t)}
                      {w.is_blocked && (
                        <div className="text-xs text-red-700" title={w.block_reason ?? ""}>⛔ {t("status.blocked")}</div>
                      )}
                    </td>
                    <td><span className="badge">{statusLabel(w.status, t)}</span></td>
                    <td>{w.actual_input_qty}</td>
                    <td>{w.actual_output_qty}</td>
                    <td>{w.failed_qty}</td>
                    <td>{w.deadline ? new Date(w.deadline).toLocaleDateString() : "—"}</td>
                    <td>{flows?.find((f) => f.id === w.sewing_flow_id)?.code ?? "—"}</td>
                    <td className="flex gap-2 flex-wrap">
                      {canPlan && w.operation === "sewing" && (
                        <button className="text-slate-700 hover:underline" onClick={() => openEdit(w)}>{t("btn.assign")}</button>
                      )}
                      {!w.is_blocked
                        ? <button className="text-red-600 hover:underline" onClick={() => blockWO(w.id)}>{t("btn.block")}</button>
                        : <button className="text-amber-700 hover:underline" onClick={() => unblockWO(w.id)}>{t("btn.unblock")}</button>}
                      {w.operation === "sewing" && (
                        <button className="text-slate-600 hover:underline" onClick={() => setOpenAssignments(openAssignments === w.id ? null : w.id)}>
                          {openAssignments === w.id ? t("btn.hideSplit") : t("btn.split")}
                        </button>
                      )}
                      {w.operation === "cutting" && <Link href={`/work-orders/${w.id}/cutting`} className="text-brand-600 hover:underline">{t("dash.cutting")}</Link>}
                      {w.operation === "printing" && <Link href={`/work-orders/${w.id}/printing`} className="text-brand-600 hover:underline">{t("dash.printing")}</Link>}
                      {w.operation === "sewing" && <Link href={`/work-orders/${w.id}/sewing`} className="text-brand-600 hover:underline">{t("dash.sewing")}</Link>}
                      {w.operation === "packaging" && <Link href={`/work-orders/${w.id}/packaging`} className="text-brand-600 hover:underline">{t("dash.packaging")}</Link>}
                    </td>
                  </tr>
                  {w.operation === "sewing" && openAssignments === w.id && (
                    <tr key={`${w.id}-assignments`}>
                      <td colSpan={9} className="bg-slate-50 p-3">
                        <SewingAssignmentsPanel woId={w.id} plannedQty={w.planned_input_qty} flows={flows ?? []} utilByFlow={utilByFlow} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing ? `${operationLabel(editing.operation, t)} #${editing.id}` : ""}>
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
                {flows?.map((f) => {
                  const u = utilByFlow.get(f.id);
                  const isFull = !!u?.is_full;
                  return (
                    <option key={f.id} value={f.id} disabled={isFull}>
                      {f.code} — {f.name}{isFull ? ` (FULL ${u?.utilization_pct ?? 100}%)` : ""}
                    </option>
                  );
                })}
              </select>
              {edit.sewing_flow_id > 0 && utilByFlow.get(edit.sewing_flow_id)?.is_full && (
                <div className="mt-1 text-xs text-red-600">{t("msg.lineFull")}</div>
              )}
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


function SewingAssignmentsPanel({
  woId,
  plannedQty,
  flows,
  utilByFlow,
}: {
  woId: number;
  plannedQty: number;
  flows: Flow[];
  utilByFlow: Map<number, FlowUtil>;
}) {
  const { t } = useT();
  const { data, mutate } = useSWR<Assignment[]>(`/api/work-orders/${woId}/assignments`, fetcher);
  const [draft, setDraft] = useState({ sewing_flow_id: 0, quantity: 0, planned_start: "", planned_end: "" });
  const [msg, setMsg] = useState("");
  const committed = (data || []).reduce((s, a) => s + a.quantity, 0);
  const remaining = Math.max(0, plannedQty - committed);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    if (draft.sewing_flow_id > 0 && utilByFlow.get(draft.sewing_flow_id)?.is_full) {
      setMsg(t("msg.selectedLineFull"));
      return;
    }
    try {
      await api.post(`/api/work-orders/${woId}/assignments`, {
        work_order_id: woId,
        sewing_flow_id: draft.sewing_flow_id,
        quantity: draft.quantity,
        planned_start: draft.planned_start ? new Date(draft.planned_start).toISOString() : null,
        planned_end: draft.planned_end ? new Date(draft.planned_end).toISOString() : null,
      });
      setDraft({ sewing_flow_id: 0, quantity: 0, planned_start: "", planned_end: "" });
      mutate();
    } catch (e: any) { setMsg(e.message); }
  }
  async function del(aid: number) {
    if (!confirm(t("confirm.deleteAssignment"))) return;
    try { await api.del(`/api/sewing-assignments/${aid}`); mutate(); }
    catch (e: any) { alert(e.message); }
  }

  return (
    <div>
      <div className="text-xs font-medium text-slate-500 uppercase mb-2">
        {t("page.poDetail.splitSummary", { committed, planned: plannedQty, remaining })}
      </div>
      <table className="table text-xs">
        <thead>
          <tr><th>{t("field.line")}</th><th>{t("field.qty")}</th><th>{t("page.poDetail.done")}</th><th>{t("field.plannedStart")}</th><th>{t("field.plannedEnd")}</th><th>{t("common.status")}</th><th></th></tr>
        </thead>
        <tbody>
          {(data || []).map((a) => (
            <tr key={a.id}>
              <td>{flows.find((f) => f.id === a.sewing_flow_id)?.code ?? a.sewing_flow_id}</td>
              <td>{a.quantity}</td>
              <td>{a.completed_qty}</td>
              <td>{a.planned_start ? new Date(a.planned_start).toLocaleDateString() : "—"}</td>
              <td>{a.planned_end ? new Date(a.planned_end).toLocaleDateString() : "—"}</td>
              <td><span className="badge">{statusLabel(a.status, t)}</span></td>
              <td><button onClick={() => del(a.id)} className="text-red-600 hover:underline">{t("tasks.delete")}</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <form onSubmit={add} className="grid grid-cols-1 md:grid-cols-6 gap-2 mt-3">
        <select className="input" value={draft.sewing_flow_id} onChange={(e) => setDraft({ ...draft, sewing_flow_id: Number(e.target.value) })} required>
          <option value={0}>{t("ph.pickLine")}</option>
          {flows.map((f) => {
            const u = utilByFlow.get(f.id);
            const isFull = !!u?.is_full;
            return (
              <option key={f.id} value={f.id} disabled={isFull}>
                {f.code} — {f.name}{isFull ? ` (FULL ${u?.utilization_pct ?? 100}%)` : ""}
              </option>
            );
          })}
        </select>
        <input className="input" type="number" placeholder={t("field.qty")} value={draft.quantity} onChange={(e) => setDraft({ ...draft, quantity: Number(e.target.value) })} required />
        <input className="input" type="date" value={draft.planned_start} onChange={(e) => setDraft({ ...draft, planned_start: e.target.value })} />
        <input className="input" type="date" value={draft.planned_end} onChange={(e) => setDraft({ ...draft, planned_end: e.target.value })} />
        <button className="btn btn-primary md:col-span-2" disabled={draft.sewing_flow_id > 0 && !!utilByFlow.get(draft.sewing_flow_id)?.is_full}>
          {t("btn.addAssignment")}
        </button>
        {draft.sewing_flow_id > 0 && utilByFlow.get(draft.sewing_flow_id)?.is_full && (
          <div className="text-sm text-red-600 md:col-span-6">{t("msg.selectedLineFull")}</div>
        )}
        {msg && <div className="text-sm text-red-600 md:col-span-6">{msg}</div>}
      </form>
    </div>
  );
}


