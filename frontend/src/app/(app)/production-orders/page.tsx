"use client";
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type PO = {
  id: number; production_no: string; production_type: string;
  model_id: number; status: string; planned_quantity: number;
  deadline: string | null;
};

const STATUSES = [
  "new", "planning", "waiting_material", "cutting", "printing", "sewing",
  "packaging", "finished_storage", "delivered", "closed", "cancelled",
];

export default function ProductionOrdersPage() {
  const { me } = useMe();
  const { t } = useT();
  const isAdmin = can(me, "*");
  const { data, mutate } = useSWR<PO[]>("/api/production-orders", fetcher);

  const [editing, setEditing] = useState<PO | null>(null);
  const [edit, setEdit] = useState({ status: "new", planned_quantity: 0, deadline: "" });
  const [editMsg, setEditMsg] = useState("");

  function openEdit(p: PO) {
    setEditing(p);
    setEdit({ status: p.status, planned_quantity: p.planned_quantity, deadline: p.deadline ? p.deadline.slice(0, 10) : "" });
    setEditMsg("");
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try {
      await api.patch(`/api/production-orders/${editing.id}`, {
        status: edit.status,
        planned_quantity: edit.planned_quantity,
        deadline: edit.deadline ? new Date(edit.deadline).toISOString() : null,
      });
      setEditing(null);
      mutate();
    } catch (e: any) { setEditMsg(e.message); }
  }

  return (
    <div>
      <PageHeader title={t("page.po.title")} />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.productionNo")}</th><th>{t("field.type")}</th><th>{t("field.model")}</th>
              <th>{t("page.poDetail.planned")}</th><th>{t("field.status")}</th>
              <th>{t("field.deadline")}</th><th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((p) => (
              <tr key={p.id}>
                <td className="font-medium">{p.production_no}</td>
                <td><span className="badge badge-blue">{p.production_type}</span></td>
                <td>{p.model_id}</td>
                <td>{p.planned_quantity}</td>
                <td><span className="badge">{p.status}</span></td>
                <td>{p.deadline ? new Date(p.deadline).toLocaleDateString() : "—"}</td>
                <td className="flex gap-3">
                  <Link href={`/production-orders/${p.id}`} className="text-brand-600 hover:underline">{t("btn.view")}</Link>
                  {isAdmin && (
                    <button className="text-slate-700 hover:underline" onClick={() => openEdit(p)}>{t("btn.edit")}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.po.editTitle", { productionNo: editing?.production_no ?? "" })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div>
            <label className="label">{t("field.status")}</label>
            <select className="input" value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t("field.plannedQty")}</label>
            <input className="input" type="number" value={edit.planned_quantity} onChange={(e) => setEdit({ ...edit, planned_quantity: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.deadline")}</label>
            <input className="input" type="date" value={edit.deadline} onChange={(e) => setEdit({ ...edit, deadline: e.target.value })} />
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
