"use client";
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type SO = {
  id: number; order_no: string; customer_id: number | null;
  order_type: string; status: string;
  deadline: string | null; total_amount: number; notes: string | null;
};

const STATUSES = ["draft", "confirmed", "planning", "production", "ready", "delivered", "closed", "cancelled"];

export default function SalesOrdersPage() {
  const { me } = useMe();
  const { t } = useT();
  const isAdmin = can(me, "*");
  const { data, isLoading, mutate } = useSWR<SO[]>("/api/sales-orders", fetcher);

  const [editing, setEditing] = useState<SO | null>(null);
  const [edit, setEdit] = useState({ status: "draft", deadline: "", notes: "" });
  const [editMsg, setEditMsg] = useState("");

  function openEdit(o: SO) {
    setEditing(o);
    setEdit({
      status: o.status,
      deadline: o.deadline ? o.deadline.slice(0, 10) : "",
      notes: o.notes ?? "",
    });
    setEditMsg("");
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try {
      await api.patch(`/api/sales-orders/${editing.id}`, {
        status: edit.status,
        deadline: edit.deadline ? new Date(edit.deadline).toISOString() : null,
        notes: edit.notes,
      });
      setEditing(null);
      mutate();
    } catch (e: any) { setEditMsg(e.message); }
  }

  return (
    <div>
      <PageHeader
        title={t("nav.salesOrders")}
        subtitle={t("page.salesOrders.subtitle")}
        actions={<Link href="/sales-orders/new" className="btn btn-primary">{t("btn.newOrder")}</Link>}
      />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.orderNo")}</th>
              <th>{t("field.type")}</th>
              <th>{t("field.status")}</th>
              <th>{t("field.deadline")}</th>
              <th>{t("field.total")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && <tr><td colSpan={6} className="text-slate-500">{t("common.loading")}</td></tr>}
            {data?.map((o) => (
              <tr key={o.id}>
                <td className="font-medium">{o.order_no}</td>
                <td><span className="badge badge-blue">{o.order_type === "client_order" ? t("orderType.client") : t("orderType.branded")}</span></td>
                <td><span className="badge">{o.status}</span></td>
                <td>{o.deadline ? new Date(o.deadline).toLocaleDateString() : "—"}</td>
                <td>${Number(o.total_amount).toFixed(2)}</td>
                <td className="flex gap-3">
                  <Link href={`/sales-orders/${o.id}`} className="text-brand-600 hover:underline">{t("btn.view")}</Link>
                  {isAdmin && (
                    <button className="text-slate-700 hover:underline" onClick={() => openEdit(o)}>{t("btn.edit")}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.soDetail.editTitle", { orderNo: editing?.order_no ?? "" })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div>
            <label className="label">{t("field.status")}</label>
            <select className="input" value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t("field.deadline")}</label>
            <input className="input" type="date" value={edit.deadline} onChange={(e) => setEdit({ ...edit, deadline: e.target.value })} />
          </div>
          <div>
            <label className="label">{t("field.notes")}</label>
            <textarea className="input" rows={3} value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />
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
