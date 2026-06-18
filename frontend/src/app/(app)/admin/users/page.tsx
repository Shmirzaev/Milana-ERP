"use client";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
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
  last_login_at: string | null;
  last_seen_at: string | null;
};

const RECENT_ACTIVITY_MS = 15 * 60 * 1000;
const ACTIVE_THIS_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

function parseActivityDate(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export default function AdminUsersPage() {
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();
  const { t, lang } = useT();
  const { data, mutate } = useSWR<User[]>("/api/users", fetcher);
  const { data: roles } = useSWR<Role[]>("/api/roles", fetcher);
  const { data: depts } = useSWR<Dept[]>("/api/departments", fetcher);
  const [nowMs, setNowMs] = useState<number | null>(null);
  const localeByLang: Record<string, string> = {
    en: "en-US",
    ru: "ru-RU",
    uz: "uz-UZ",
  };
  const locale = localeByLang[lang] || "en-US";

  useEffect(() => {
    const updateNow = () => setNowMs(Date.now());
    updateNow();
    const id = window.setInterval(updateNow, 60_000);
    return () => window.clearInterval(id);
  }, []);

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
  const [deleting, setDeleting] = useState<User | null>(null);

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

  function deleteUser(u: User) {
    setDeleting(u);
  }

  async function confirmDeleteUser() {
    if (!deleting) return;
    try {
      await api.del(`/api/users/${deleting.id}`);
      setDeleting(null);
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

  const activityStats = useMemo(() => {
    if (nowMs === null) return { onlineRecently: 0, activeThisWeek: 0, notUsing: 0 };
    return (data ?? []).reduce(
      (acc, u) => {
        const seenAt = parseActivityDate(u.last_seen_at ?? u.last_login_at);
        if (!seenAt) {
          acc.notUsing += 1;
          return acc;
        }
        const age = nowMs - seenAt.getTime();
        if (age <= RECENT_ACTIVITY_MS) acc.onlineRecently += 1;
        if (age <= ACTIVE_THIS_WEEK_MS) acc.activeThisWeek += 1;
        else acc.notUsing += 1;
        return acc;
      },
      { onlineRecently: 0, activeThisWeek: 0, notUsing: 0 },
    );
  }, [data, nowMs]);

  function formatActivityTime(value?: string | null) {
    const date = parseActivityDate(value);
    if (!date) return t("field.never");
    return date.toLocaleString(locale, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function activityBadge(u: User) {
    const seenAt = parseActivityDate(u.last_seen_at ?? u.last_login_at);
    if (!seenAt) return { className: "badge-red", label: t("status.neverLoggedIn") };
    if (nowMs === null) return { className: "badge-blue", label: t("status.activeThisWeek") };
    const age = nowMs - seenAt.getTime();
    if (age <= RECENT_ACTIVITY_MS) return { className: "badge-green", label: t("status.onlineRecently") };
    if (age <= ACTIVE_THIS_WEEK_MS) return { className: "badge-blue", label: t("status.activeThisWeek") };
    return { className: "badge-yellow", label: t("status.notUsing") };
  }

  return (
    <div>
      <PageHeader title={t("page.admin.users")} />

      <form onSubmit={create} autoComplete="off" className="card mb-6 grid grid-cols-1 gap-3 p-4 md:grid-cols-6">
        <input className="input" placeholder={t("common.name")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        <input className="input" name="new_user_email" autoComplete="off" placeholder={t("auth.email")} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required />
        <input className="input" name="new_user_password" autoComplete="new-password" placeholder={t("auth.password")} type="password" minLength={12} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
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

      <dl className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="panel p-4">
          <dt className="label">{t("page.admin.users.onlineRecently")}</dt>
          <dd className="mono text-2xl font-semibold text-[#1f7a4d]">{activityStats.onlineRecently}</dd>
        </div>
        <div className="panel p-4">
          <dt className="label">{t("page.admin.users.activeThisWeek")}</dt>
          <dd className="mono text-2xl font-semibold text-[#1e5fb3]">{activityStats.activeThisWeek}</dd>
        </div>
        <div className="panel p-4">
          <dt className="label">{t("page.admin.users.notUsing")}</dt>
          <dd className="mono text-2xl font-semibold text-[#9a3308]">{activityStats.notUsing}</dd>
        </div>
      </dl>

      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name")}</th>
              <th>{t("auth.email")}</th>
              <th>{t("field.role")}</th>
              <th>{t("field.department")}</th>
              <th>{t("field.active")}</th>
              <th>{t("field.activity")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => {
              const badge = activityBadge(u);
              return (
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
                  <td className="min-w-[180px]">
                    <div className="flex flex-col gap-1">
                      <span className={`badge w-fit ${badge.className}`}>{badge.label}</span>
                      <span className="text-xs text-[#56503f]">
                        {t("field.lastSeen")}: {formatActivityTime(u.last_seen_at ?? u.last_login_at)}
                      </span>
                      <span className="text-xs text-[#8a8472]">
                        {t("field.lastLogin")}: {formatActivityTime(u.last_login_at)}
                      </span>
                    </div>
                  </td>
                  <td className="flex gap-2">
                    <button className="text-brand-600 hover:underline" onClick={() => openEdit(u)}>{t("btn.edit")}</button>
                    <button className="text-red-600 hover:underline" onClick={() => deleteUser(u)}>{t("btn.delete")}</button>
                  </td>
                </tr>
              );
            })}
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
            <input className="input" type="password" minLength={12} value={edit.password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} autoComplete="new-password" />
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
      <ConfirmDialog
        isOpen={!!deleting}
        title={t("confirm.deleteTitle")}
        message={deleting ? t("confirm.deleteUser", { name: deleting.email }) : ""}
        onConfirm={confirmDeleteUser}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
