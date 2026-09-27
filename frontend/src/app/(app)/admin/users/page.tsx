"use client";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
import { useT } from "@/lib/i18n";
import { useMe } from "@/lib/auth";
import { useDialogs } from "@/components/DialogProvider";
import UserAccessEditor from "@/components/UserAccessEditor";
import { type AccessPolicy } from "@/lib/userAccess";

type Role = { id: number; name: string; permissions: string[] };
type Dept = { id: number; name: string; is_active?: boolean };
type User = {
  id: number;
  name: string;
  email: string;
  role_id: number | null;
  department_id: number | null;
  factory_code: "MIL" | "BST" | "ECO";
  extra_permissions: string[];
  access_policy: AccessPolicy | null;
  is_active: boolean;
  last_login_at: string | null;
  last_seen_at: string | null;
};

const SUPER_ADMIN_PERMISSION = "admin.super";

const RECENT_ACTIVITY_MS = 15 * 60 * 1000;
const ACTIVE_THIS_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

function parseActivityDate(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function uniquePermissions(values: string[]) {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const permission = value.trim();
    if (!permission || seen.has(permission)) continue;
    seen.add(permission);
    out.push(permission);
  }
  return out;
}

function roleIsAdministrator(role: Role | undefined) {
  const permissions = new Set(role?.permissions ?? []);
  return permissions.has("*") || permissions.has(SUPER_ADMIN_PERMISSION) || (role?.name ?? "").trim().toLowerCase() === "super admin";
}

export default function AdminUsersPage() {
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();
  const { t, lang } = useT();
  const dialogs = useDialogs();
  const { me, refresh: refreshMe } = useMe();
  const [createAccessReady, setCreateAccessReady] = useState(false);
  const [editAccessReady, setEditAccessReady] = useState(false);
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
  const canManageAdmins = Boolean(me?.permissions.includes(SUPER_ADMIN_PERMISSION));

  useEffect(() => {
    const updateNow = () => setNowMs(Date.now());
    updateNow();
    const id = window.setInterval(updateNow, 60_000);
    return () => window.clearInterval(id);
  }, []);

  const [f, setF] = useState({
    name: "",
    email: "",
    role_id: 0,
    department_id: 0,
    factory_code: "MIL" as "MIL" | "BST" | "ECO",
    is_active: true,
    access_policy: {} as AccessPolicy | null,
  });
  const [createMsg, setCreateMsg] = useState("");
  const [createError, setCreateError] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!createAccessReady) return;
    setCreateMsg("");
    setCreateError(false);
    try {
      await api.post("/api/users", {
        ...f,
        role_id: f.role_id || null,
        department_id: f.department_id || null,
      });
      mutate();
      setF({ name: "", email: "", role_id: 0, department_id: 0, factory_code: "MIL", is_active: true, access_policy: {} });
      setCreateMsg(t("page.admin.users.setupEmailQueued"));
    } catch (e: any) {
      setCreateError(true);
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
    factory_code: "MIL" as "MIL" | "BST" | "ECO",
    extra_permissions: [] as string[],
    access_policy: null as AccessPolicy | null,
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
      factory_code: u.factory_code || "MIL",
      extra_permissions: uniquePermissions(u.extra_permissions ?? []),
      access_policy: u.access_policy ?? null,
      is_active: u.is_active,
    });
    setEditMsg("");
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing || !editAccessReady) return;
    setEditMsg("");
    try {
      const payload: any = {
        name: edit.name,
        email: edit.email,
        role_id: edit.role_id || null,
        department_id: edit.department_id || null,
        factory_code: edit.factory_code,
        extra_permissions: uniquePermissions(edit.extra_permissions),
        access_policy: edit.access_policy,
        is_active: edit.is_active,
      };
      if (edit.password.trim()) payload.password = edit.password;
      await api.patch(`/api/users/${editing.id}`, payload);
      setEditing(null);
      mutate();
      refreshMe();
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
      await dialogs.notify(e.message);
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

      <form onSubmit={create} autoComplete="off" className="card mb-6 grid grid-cols-1 gap-3 p-4 md:grid-cols-5">
        <input className="input" placeholder={t("common.name")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        <input className="input" name="new_user_email" autoComplete="off" placeholder={t("auth.email")} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required />
        <select className="input" value={f.role_id} onChange={(e) => setF({ ...f, role_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.role")}</option>
          {roles?.map((r) => {
            const restricted = roleIsAdministrator(r) && !canManageAdmins;
            return (
              <option key={r.id} value={r.id} disabled={restricted}>
                {r.name}{restricted ? ` (${t("page.admin.users.superAdminOnly")})` : ""}
              </option>
            );
          })}
        </select>
        <select className="input" value={f.department_id} onChange={(e) => setF({ ...f, department_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.dept")}</option>
          {depts?.filter((d) => d.is_active !== false).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select className="input" value={f.factory_code} onChange={(e) => setF({ ...f, factory_code: e.target.value as "MIL" | "BST" | "ECO" })}>
          <option value="MIL">Milana</option><option value="BST">Besttex</option><option value="ECO">Eco Cotton</option>
        </select>
        <div className="md:col-span-5">
          <UserAccessEditor subject={{ ...f, role_id: f.role_id || null, department_id: f.department_id || null }}
            value={f.access_policy} onChange={(access_policy) => setF((current) => ({ ...current, access_policy }))} onReady={setCreateAccessReady} />
        </div>
        <button className="btn btn-primary" disabled={!createAccessReady}>{t("btn.create")}</button>
        {createMsg && <div className={`text-sm ${createError ? "text-red-600" : "text-green-700"} md:col-span-5`}>{createMsg}</div>}
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
              <th>Factory</th>
              <th>{t("field.active")}</th>
              <th>{t("field.activity")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => {
              const badge = activityBadge(u);
              const role = roles?.find((r) => r.id === u.role_id);
              const adminAccount = roleIsAdministrator(role);
              const restrictedAdminAccount = adminAccount && !canManageAdmins && u.id !== me?.id;
              return (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td>{u.email}</td>
                  <td>{role?.name ?? u.role_id ?? "-"}</td>
                  <td>{depts?.find((d) => d.id === u.department_id)?.name ?? u.department_id ?? "-"}</td>
                  <td>{u.factory_code}</td>
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
                    <button
                      className={`text-brand-600 hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:no-underline`}
                      disabled={restrictedAdminAccount}
                      title={restrictedAdminAccount ? t("page.admin.users.superAdminOnly") : undefined}
                      onClick={() => openEdit(u)}
                    >
                      {t("btn.edit")}
                    </button>
                    <button
                      className="text-red-600 hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:no-underline"
                      disabled={adminAccount && !canManageAdmins}
                      title={adminAccount && !canManageAdmins ? t("page.admin.users.superAdminOnly") : undefined}
                      onClick={() => deleteUser(u)}
                    >
                      {t("btn.delete")}
                    </button>
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
                {roles?.map((r) => {
                  const restricted = roleIsAdministrator(r) && !canManageAdmins;
                  return (
                    <option key={r.id} value={r.id} disabled={restricted}>
                      {r.name}{restricted ? ` (${t("page.admin.users.superAdminOnly")})` : ""}
                    </option>
                  );
                })}
              </select>
            </div>
            <div>
              <label className="label">{t("field.department")}</label>
              <select className="input" value={edit.department_id} onChange={(e) => setEdit({ ...edit, department_id: Number(e.target.value) })}>
                <option value={0}>-</option>
                {depts?.filter((d) => d.is_active !== false || d.id === edit.department_id).map((d) => <option key={d.id} value={d.id}>{d.name}{d.is_active === false ? ` (${t("field.inactive")})` : ""}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Factory</label>
              <select className="input" value={edit.factory_code} onChange={(e) => setEdit({ ...edit, factory_code: e.target.value as "MIL" | "BST" | "ECO" })}>
                <option value="MIL">Milana</option><option value="BST">Besttex</option><option value="ECO">Eco Cotton</option>
              </select>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} />
            {t("field.active")}
          </label>
          <UserAccessEditor subject={{ ...edit, role_id: edit.role_id || null, department_id: edit.department_id || null }}
            value={edit.access_policy} onChange={(access_policy) => setEdit((current) => ({ ...current, access_policy }))} onReady={setEditAccessReady} />
          {editMsg && <div className="text-sm text-red-600">{editMsg}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={() => setEditing(null)}>{t("btn.cancel")}</button>
            <button type="submit" className="btn btn-primary" disabled={!editAccessReady}>{t("btn.saveChanges")}</button>
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
