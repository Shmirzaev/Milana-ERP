"use client";
import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type Model = {
  id: number; code: string; name: string;
  category?: string | null; description?: string | null;
  status: string; created_at: string;
  sam_minutes?: number;
};

const STATUSES = ["draft", "sample", "approved", "archived"];

export default function ModelsPage() {
  const searchParams = useSearchParams();
  const q = searchParams.get("q")?.trim() ?? "";
  const { me } = useMe();
  const { t } = useT();
  const isAdmin = can(me, "*");
  const modelsUrl = q ? `/api/models?q=${encodeURIComponent(q)}` : "/api/models";
  const { data, mutate } = useSWR<Model[]>(modelsUrl, fetcher);

  const [form, setForm] = useState({ code: "", name: "", category: "", sam_minutes: 0 });
  const [err, setErr] = useState("");

  const [editing, setEditing] = useState<Model | null>(null);
  const [edit, setEdit] = useState({ code: "", name: "", category: "", description: "", status: "draft", sam_minutes: 0 });
  const [editMsg, setEditMsg] = useState("");

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    try { await api.post("/api/models", form); setForm({ code: "", name: "", category: "", sam_minutes: 0 }); mutate(); }
    catch (e: any) { setErr(e.message); }
  }
  async function approve(id: number) { await api.post(`/api/models/${id}/approve`); mutate(); }
  function openEdit(m: Model) {
    setEditing(m);
    setEdit({ code: m.code, name: m.name, category: m.category ?? "", description: m.description ?? "", status: m.status, sam_minutes: Number(m.sam_minutes ?? 0) });
    setEditMsg("");
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try { await api.patch(`/api/models/${editing.id}`, edit); setEditing(null); mutate(); }
    catch (e: any) { setEditMsg(e.message); }
  }

  async function removeModel(m: Model) {
    if (!confirm(`${t("common.delete")} ${m.code} - ${m.name}?`)) return;
    try {
      await api.del(`/api/models/${m.id}`);
      if (editing?.id === m.id) setEditing(null);
      mutate();
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.models.title")} subtitle={t("page.models.subtitle")} />
      <form onSubmit={create} className="card p-4 mb-6 grid grid-cols-1 md:grid-cols-5 gap-3">
        <input className="input" placeholder={t("common.code")} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
        <input className="input" placeholder={t("common.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <input className="input" placeholder={t("field.category")} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
        <input className="input" type="number" step="0.1" placeholder={t("field.samMinutes")} value={form.sam_minutes} onChange={(e) => setForm({ ...form, sam_minutes: Number(e.target.value) })} title={t("field.samHint")} />
        <button className="btn btn-primary">{t("btn.createDraftModel")}</button>
        {err && <div className="md:col-span-5 text-sm text-red-600">{err}</div>}
      </form>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code")}</th><th>{t("common.name")}</th>
              <th>{t("field.status")}</th><th>{t("field.sam")}</th><th>{t("field.created")}</th><th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((m) => (
              <tr key={m.id}>
                <td className="font-medium">{m.code}</td>
                <td>{m.name}</td>
                <td><span className={`badge ${m.status === "approved" ? "badge-green" : "badge-yellow"}`}>{t(`modelStatus.${m.status}`)}</span></td>
                <td>{Number(m.sam_minutes ?? 0)}</td>
                <td>{new Date(m.created_at).toLocaleDateString()}</td>
                <td className="flex gap-3 flex-wrap">
                  <Link href={`/models/${m.id}`} className="text-brand-600 hover:underline">{t("btn.view")}</Link>
                  {m.status !== "approved" && (
                    <button className="text-green-700 hover:underline" onClick={() => approve(m.id)}>{t("btn.approve")}</button>
                  )}
                  {isAdmin && (
                    <>
                      <button type="button" className="text-slate-700 hover:underline" onClick={() => openEdit(m)}>{t("btn.edit")}</button>
                      <button type="button" className="text-red-600 hover:underline" onClick={() => removeModel(m)}>{t("common.delete")}</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.models.editTitle", { code: editing?.code ?? "" })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label">{t("common.code")}</label><input className="input" value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.target.value })} required /></div>
            <div><label className="label">{t("common.name")}</label><input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required /></div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div><label className="label">{t("field.category")}</label><input className="input" value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })} /></div>
            <div>
              <label className="label">{t("field.status")}</label>
              <select className="input" value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                {STATUSES.map((s) => <option key={s} value={s}>{t(`modelStatus.${s}`)}</option>)}
              </select>
            </div>
            <div>
              <label className="label" title={t("field.samHint")}>{t("field.samMinutes")}</label>
              <input className="input" type="number" step="0.1" value={edit.sam_minutes} onChange={(e) => setEdit({ ...edit, sam_minutes: Number(e.target.value) })} />
            </div>
          </div>
          <div><label className="label">{t("field.description")}</label><textarea className="input" rows={3} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></div>
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
