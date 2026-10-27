"use client";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { statusLabel } from "@/components/StagePipeline";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { numberOrFallback, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";

type Collection = {
  id: number; brand_id: number; name: string;
  season?: string | null; year?: number | null; description?: string | null; status: string;
};

export default function CollectionsPage() {
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();
  const { me } = useMe();
  const { t } = useT();
  const isAdmin = can(me, "*");
  const { data, mutate } = useSWR<Collection[]>("/api/collections", fetcher);
  const { data: brands } = useSWR<any[]>("/api/brands", fetcher);
  const [form, setForm] = useState<{ brand_id: number; name: string; season: string; year: NumberInputValue }>({ brand_id: 0, name: "", season: "", year: 2025 });

  const [editing, setEditing] = useState<Collection | null>(null);
  const [edit, setEdit] = useState<{ brand_id: number; name: string; season: string; year: NumberInputValue; description: string; status: string }>({ brand_id: 0, name: "", season: "", year: 2025, description: "", status: "draft" });
  const [editMsg, setEditMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await api.post("/api/collections", { ...form, year: numberOrFallback(form.year, 2025) });
    setForm({ brand_id: 0, name: "", season: "", year: 2025 });
    mutate();
  }
  function openEdit(c: Collection) {
    setEditing(c);
    setEdit({
      brand_id: c.brand_id, name: c.name,
      season: c.season ?? "", year: c.year ?? 2025,
      description: c.description ?? "", status: c.status,
    });
    setEditMsg("");
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try { await api.patch(`/api/collections/${editing.id}`, { ...edit, year: numberOrFallback(edit.year, 2025) }); setEditing(null); mutate(); }
    catch (e: any) { setEditMsg(e.message); }
  }

  const rows = useMemo(() => {
    if (!data) return [];
    if (!q) return data;
    return data.filter((c) => {
      const brand = (brands?.find((b) => b.id === c.brand_id)?.name ?? "").toLowerCase();
      return (
        (c.name ?? "").toLowerCase().includes(q) ||
        (c.season ?? "").toLowerCase().includes(q) ||
        String(c.year ?? "").toLowerCase().includes(q) ||
        (c.status ?? "").toLowerCase().includes(q) ||
        brand.includes(q)
      );
    });
  }, [data, brands, q]);

  return (
    <div>
      <PageHeader title={t("page.collections.title")} />
      <form onSubmit={submit} className="card mb-6 grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 xl:grid-cols-5">
        <select className="input" value={form.brand_id} onChange={(e) => setForm({ ...form, brand_id: Number(e.target.value) })} required>
          <option value={0}>{t("ph.brand")}</option>
          {brands?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <input className="input" placeholder={t("common.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <input className="input" placeholder={t("field.season")} value={form.season} onChange={(e) => setForm({ ...form, season: e.target.value })} />
        <input className="input" type="number" placeholder={t("field.year")} value={form.year} onChange={(e) => setForm({ ...form, year: parseNumberInput(e.target.value) })} required />
        <button className="btn btn-primary">{t("btn.create")}</button>
      </form>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.brand")}</th><th>{t("common.name")}</th><th>{t("field.season")}</th>
              <th>{t("field.year")}</th><th>{t("field.status")}</th>
              {isAdmin && <th>{t("field.actions")}</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td>{brands?.find((b) => b.id === c.brand_id)?.name ?? c.brand_id}</td>
                <td>{c.name}</td><td>{c.season}</td><td>{c.year}</td>
                <td><span className="badge">{statusLabel(c.status, t)}</span></td>
                {isAdmin && (
                  <td><button className="text-brand-600 hover:underline" onClick={() => openEdit(c)}>{t("btn.edit")}</button></td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.collections.editTitle", { name: editing?.name ?? "" })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">{t("field.brand")}</label>
              <select className="input" value={edit.brand_id} onChange={(e) => setEdit({ ...edit, brand_id: Number(e.target.value) })}>
                {brands?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">{t("common.name")}</label>
              <input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div><label className="label">{t("field.season")}</label><input className="input" value={edit.season} onChange={(e) => setEdit({ ...edit, season: e.target.value })} /></div>
            <div><label className="label">{t("field.year")}</label><input className="input" type="number" value={edit.year} onChange={(e) => setEdit({ ...edit, year: parseNumberInput(e.target.value) })} required /></div>
            <div>
              <label className="label">{t("field.status")}</label>
              <select className="input" value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                <option value="draft">{t("modelStatus.draft")}</option>
                <option value="approved">{t("modelStatus.approved")}</option>
                <option value="archived">{t("modelStatus.archived")}</option>
              </select>
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
