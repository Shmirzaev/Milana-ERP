"use client";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Pencil, Trash2, X, Check } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import ConfirmDialog from "@/components/ConfirmDialog";
import { useT } from "@/lib/i18n";

type Department = { id: number; name: string; code: string };

export default function DepartmentsPage() {
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();
  const { t } = useT();
  const { data, mutate } = useSWR<Department[]>("/api/departments", fetcher);
  const [f, setF] = useState({ name: "", code: "" });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [edit, setEdit] = useState({ name: "", code: "" });
  const [msg, setMsg] = useState("");
  const [deleting, setDeleting] = useState<Department | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      await api.post("/api/departments", { name: f.name.trim(), code: f.code.trim().toUpperCase() });
      setF({ name: "", code: "" });
      mutate();
    } catch (e: any) {
      setMsg(e.message || t("departments.addFailed"));
    }
  }

  function startEdit(d: Department) {
    setEditingId(d.id);
    setEdit({ name: d.name, code: d.code });
    setMsg("");
  }

  async function saveEdit(id: number) {
    setMsg("");
    try {
      await api.patch(`/api/departments/${id}`, {
        name: edit.name.trim(),
        code: edit.code.trim().toUpperCase(),
      });
      setEditingId(null);
      mutate();
    } catch (e: any) {
      setMsg(e.message || t("departments.updateFailed"));
    }
  }

  function removeDepartment(d: Department) {
    setDeleting(d);
  }

  async function confirmRemoveDepartment() {
    if (!deleting) return;
    setMsg("");
    try {
      await api.del(`/api/departments/${deleting.id}`);
      if (editingId === deleting.id) setEditingId(null);
      setDeleting(null);
      mutate();
    } catch (e: any) {
      setMsg(e.message || t("departments.deleteFailed"));
    }
  }

  const rows = useMemo(() => {
    if (!data) return [];
    if (!q) return data;
    return data.filter((d) => (d.name ?? "").toLowerCase().includes(q) || (d.code ?? "").toLowerCase().includes(q));
  }, [data, q]);

  return (
    <div>
      <PageHeader title={t("page.admin.depts")} subtitle={t("departments.subtitle")} />
      <form onSubmit={submit} className="card mb-6 grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
        <input
          className="input"
          placeholder={t("common.name")}
          value={f.name}
          onChange={(e) => setF({ ...f, name: e.target.value })}
          required
        />
        <input
          className="input"
          placeholder={t("common.code")}
          value={f.code}
          onChange={(e) => setF({ ...f, code: e.target.value })}
          required
        />
        <button className="btn btn-primary">{t("btn.add")}</button>
      </form>
      {msg ? <div className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{msg}</div> : null}
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code")}</th>
              <th>{t("common.name")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => {
              const editing = editingId === d.id;
              return (
                <tr key={d.id}>
                  <td>
                    {editing ? (
                      <input
                        className="input"
                        value={edit.code}
                        onChange={(e) => setEdit({ ...edit, code: e.target.value })}
                      />
                    ) : d.code}
                  </td>
                  <td>
                    {editing ? (
                      <input
                        className="input"
                        value={edit.name}
                        onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                      />
                    ) : d.name}
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      {editing ? (
                        <>
                          <button type="button" className="btn" onClick={() => saveEdit(d.id)}><Check />{t("common.save")}</button>
                          <button type="button" className="btn" onClick={() => setEditingId(null)}><X />{t("common.cancel")}</button>
                        </>
                      ) : (
                        <>
                          <button type="button" className="btn" onClick={() => startEdit(d)}><Pencil />{t("common.edit")}</button>
                          <button type="button" className="btn btn-danger" onClick={() => removeDepartment(d)}><Trash2 />{t("common.delete")}</button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ConfirmDialog
        isOpen={!!deleting}
        title={t("confirm.deleteTitle")}
        message={deleting ? t("confirm.deleteDepartment", { name: `${deleting.code} (${deleting.name})` }) : ""}
        onConfirm={confirmRemoveDepartment}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}

