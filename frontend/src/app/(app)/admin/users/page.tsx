"use client";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";

type Role = { id: number; name: string };
type Dept = { id: number; name: string };
type User = {
  id: number;
  name: string;
  email: string;
  role_id: number | null;
  department_id: number | null;
  is_active: boolean;
};

export default function AdminUsersPage() {
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();
  const { t } = useT();
  const { data, mutate } = useSWR<User[]>("/api/users", fetcher);
  const { data: roles } = useSWR<Role[]>("/api/roles", fetcher);
  const { data: depts } = useSWR<Dept[]>("/api/departments", fetcher);

  const [f, setF] = useState({
    name: "",
    email: "",
    password: "",
    role_id: 0,
    department_id: 0,
    is_active: true,
  });
  const [createMsg, setCreateMsg] = useState("");

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setCreateMsg("");
    try {
      await api.post("/api/users", {
        ...f,
        role_id: f.role_id || null,
        department_id: f.department_id || null,
      });
      mutate();
      setF({ name: "", email: "", password: "", role_id: 0, department_id: 0, is_active: true });
    } catch (e: any) {
      setCreateMsg(e.message);
    }
  }

  const [editing, setEditing] = useState<User | null>(null);
  const [edit, setEdit] = useState({
    name: "",
    email: "",
    password: "",
    role_id: 0,
    department_id: 0,
    is_active: true,
  });
  const [editMsg, setEditMsg] = useState("");

  function openEdit(u: User) {
    setEditing(u);
    setEdit({
      name: u.name,
      email: u.email,
      password: "",
      role_id: u.role_id ?? 0,
      department_id: u.department_id ?? 0,
      is_active: u.is_active,
    });
    setEditMsg("");
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try {
      const payload: any = {
        name: edit.name,
        email: edit.email,
        role_id: edit.role_id || null,
        department_id: edit.department_id || null,
        is_active: edit.is_active,
      };
      if (edit.password.trim()) payload.password = edit.password;
      await api.patch(`/api/users/${editing.id}`, payload);
      setEditing(null);
      mutate();
    } catch (e: any) {
      setEditMsg(e.message);
    }
  }

  async function deleteUser(u: User) {
    if (!confirm(`${t("common.delete")} ${u.email}?`)) return;
    try {
      await api.del(`/api/users/${u.id}`);
      mutate();
    } catch (e: any) {
      alert(e.message);
    }
  }

  const rows = useMemo(() => {
    if (!data) return [];
    if (!q) return data;
    return data.filter((u) => {
      const roleName = (roles?.find((r) => r.id === u.role_id)?.name ?? "").toLowerCase();
      const deptName = (depts?.find((d) => d.id === u.department_id)?.name ?? "").toLowerCase();
      return (
        (u.name ?? "").toLowerCase().includes(q) ||
        (u.email ?? "").toLowerCase().includes(q) ||
        roleName.includes(q) ||
        deptName.includes(q)
      );
    });
  }, [data, roles, depts, q]);

  return (
    <div>
      <PageHeader title={t("page.admin.users")} />

      <form onSubmit={create} className="card mb-6 grid grid-cols-1 gap-3 p-4 md:grid-cols-6">
        <input className="input" placeholder={t("common.name")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        <input className="input" placeholder={t("auth.email")} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required />
        <input className="input" placeholder={t("auth.password")} type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
        <select className="input" value={f.role_id} onChange={(e) => setF({ ...f, role_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.role")}</option>
          {roles?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select className="input" value={f.department_id} onChange={(e) => setF({ ...f, department_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.dept")}</option>
          {depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <button className="btn btn-primary">{t("btn.create")}</button>
        {createMsg && <div className="text-sm text-red-600 md:col-span-6">{createMsg}</div>}
      </form>

      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name")}</th>
              <th>{t("auth.email")}</th>
              <th>{t("field.role")}</th>
              <th>{t("field.department")}</th>
              <th>{t("field.active")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => (
              <tr key={u.id}>
                <td>{u.name}</td>
                <td>{u.email}</td>
                <td>{roles?.find((r) => r.id === u.role_id)?.name ?? u.role_id ?? "-"}</td>
                <td>{depts?.find((d) => d.id === u.department_id)?.name ?? u.department_id ?? "-"}</td>
                <td>
                  <span className={`badge ${u.is_active ? "badge-green" : "badge-red"}`}>
                    {u.is_active ? t("field.yes") : t("field.no")}
                  </span>
                </td>
                <td className="flex gap-2">
                  <button className="text-brand-600 hover:underline" onClick={() => openEdit(u)}>{t("btn.edit")}</button>
                  <button className="text-red-600 hover:underline" onClick={() => deleteUser(u)}>{t("btn.delete")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.admin.users.editTitle", { email: editing?.email ?? "" })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div>
            <label className="label">{t("common.name")}</label>
            <input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
          </div>
          <div>
            <label className="label">{t("auth.email")}</label>
            <input className="input" type="email" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} required />
          </div>
          <div>
            <label className="label">{t("page.admin.users.newPassword")}</label>
            <input className="input" type="password" value={edit.password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} autoComplete="new-password" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">{t("field.role")}</label>
              <select className="input" value={edit.role_id} onChange={(e) => setEdit({ ...edit, role_id: Number(e.target.value) })}>
                <option value={0}>-</option>
                {roles?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">{t("field.department")}</label>
              <select className="input" value={edit.department_id} onChange={(e) => setEdit({ ...edit, department_id: Number(e.target.value) })}>
                <option value={0}>-</option>
                {depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} />
            {t("field.active")}
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
