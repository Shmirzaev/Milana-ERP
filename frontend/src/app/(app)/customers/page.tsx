"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type Customer = { id: number; name: string; phone: string | null; email: string | null; address: string | null; notes?: string | null };
const EMPTY = { name: "", phone: "", email: "", address: "", notes: "" };

export default function CustomersPage() {
  const { me } = useMe();
  const { t } = useT();
  const isAdmin = can(me, "*");
  const { data, mutate } = useSWR<Customer[]>("/api/customers", fetcher);
  const [form, setForm] = useState(EMPTY);
  const [err, setErr] = useState("");

  const [editing, setEditing] = useState<Customer | null>(null);
  const [edit, setEdit] = useState(EMPTY);
  const [editMsg, setEditMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    try { await api.post("/api/customers", form); setForm(EMPTY); mutate(); }
    catch (e: any) { setErr(e.message); }
  }

  function openEdit(c: Customer) {
    setEditing(c);
    setEdit({ name: c.name, phone: c.phone ?? "", email: c.email ?? "", address: c.address ?? "", notes: c.notes ?? "" });
    setEditMsg("");
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try { await api.patch(`/api/customers/${editing.id}`, edit); setEditing(null); mutate(); }
    catch (e: any) { setEditMsg(e.message); }
  }

  return (
    <div>
      <PageHeader title={t("page.customers.title")} />
      <form onSubmit={submit} className="card p-4 mb-6 grid grid-cols-1 md:grid-cols-5 gap-3">
        <input className="input" placeholder={t("common.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <input className="input" placeholder={t("field.phone")} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        <input className="input" placeholder={t("field.email")} type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <input className="input" placeholder={t("field.address")} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
        <button className="btn btn-primary">{t("btn.add")}</button>
        {err && <div className="md:col-span-5 text-sm text-red-600">{err}</div>}
      </form>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name")}</th><th>{t("field.phone")}</th>
              <th>{t("field.email")}</th><th>{t("field.address")}</th>
              {isAdmin && <th>{t("field.actions")}</th>}
            </tr>
          </thead>
          <tbody>
            {data?.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td><td>{c.phone}</td><td>{c.email}</td><td>{c.address}</td>
                {isAdmin && (
                  <td><button className="text-brand-600 hover:underline" onClick={() => openEdit(c)}>{t("btn.edit")}</button></td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.customers.editTitle", { name: editing?.name ?? "" })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div><label className="label">{t("common.name")}</label><input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label">{t("field.phone")}</label><input className="input" value={edit.phone} onChange={(e) => setEdit({ ...edit, phone: e.target.value })} /></div>
            <div><label className="label">{t("field.email")}</label><input className="input" type="email" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></div>
          </div>
          <div><label className="label">{t("field.address")}</label><input className="input" value={edit.address} onChange={(e) => setEdit({ ...edit, address: e.target.value })} /></div>
          <div><label className="label">{t("field.notes")}</label><textarea className="input" rows={3} value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></div>
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
