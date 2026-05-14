"use client";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type Brand = { id: number; name: string; description?: string | null; is_active: boolean };

export default function BrandsPage() {
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();
  const { me } = useMe();
  const { t } = useT();
  const isAdmin = can(me, "*");
  const { data, mutate } = useSWR<Brand[]>("/api/brands", fetcher);
  const [form, setForm] = useState({ name: "", description: "" });
  const [editing, setEditing] = useState<Brand | null>(null);
  const [edit, setEdit] = useState({ name: "", description: "", is_active: true });
  const [editMsg, setEditMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await api.post("/api/brands", form);
    setForm({ name: "", description: "" });
    mutate();
  }
  function openEdit(b: Brand) {
    setEditing(b);
    setEdit({ name: b.name, description: b.description ?? "", is_active: b.is_active });
    setEditMsg("");
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try { await api.patch(`/api/brands/${editing.id}`, edit); setEditing(null); mutate(); }
    catch (e: any) { setEditMsg(e.message); }
  }

  const rows = useMemo(() => {
    if (!data) return [];
    if (!q) return data;
    return data.filter((b) => {
      const name = (b.name ?? "").toLowerCase();
      const desc = (b.description ?? "").toLowerCase();
      return name.includes(q) || desc.includes(q);
    });
  }, [data, q]);

  return (
    <div>
      <PageHeader title={t("page.brands.title")} />
      <form onSubmit={submit} className="card p-4 mb-6 grid grid-cols-1 md:grid-cols-3 gap-3">
        <input className="input" placeholder={t("page.brands.title")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <input className="input" placeholder={t("field.description")} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <button className="btn btn-primary">{t("btn.create")}</button>
      </form>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name")}</th><th>{t("field.description")}</th><th>{t("field.status")}</th>
              {isAdmin && <th>{t("field.actions")}</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id}>
                <td>{b.name}</td>
                <td>{b.description}</td>
                <td><span className={`badge ${b.is_active ? "badge-green" : "badge-red"}`}>{b.is_active ? t("field.active") : t("field.inactive")}</span></td>
                {isAdmin && (
                  <td><button className="text-brand-600 hover:underline" onClick={() => openEdit(b)}>{t("btn.edit")}</button></td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.brands.editTitle", { name: editing?.name ?? "" })}>
        <form onSubmit={saveEdit} className="space-y-3">
          <div><label className="label">{t("common.name")}</label><input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required /></div>
          <div><label className="label">{t("field.description")}</label><textarea className="input" rows={3} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></div>
          <label className="text-sm flex items-center gap-2">
            <input type="checkbox" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} /> {t("field.active")}
          </label>
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
