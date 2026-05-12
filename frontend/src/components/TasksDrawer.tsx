"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type Task = {
  id: number;
  title: string;
  description: string | null;
  assigned_to: number | null;
  created_by: number | null;
  status: "pending" | "in_progress" | "completed" | "cancelled";
  priority: "low" | "medium" | "high" | "urgent";
  due_date: string | null;
};

const PRIORITY_BADGE: Record<Task["priority"], string> = {
  low: "bg-slate-100 text-slate-700",
  medium: "bg-blue-100 text-blue-800",
  high: "bg-orange-100 text-orange-800",
  urgent: "bg-red-100 text-red-800",
};

const STATUS_BADGE: Record<Task["status"], string> = {
  pending: "bg-slate-100 text-slate-700",
  in_progress: "bg-yellow-100 text-yellow-800",
  completed: "bg-green-100 text-green-800",
  cancelled: "bg-slate-100 text-slate-500 line-through",
};

export default function TasksDrawer() {
  const { me } = useMe();
  const { t } = useT();
  const isManager = can(me, "*", "tasks.manage", "management.approve");

  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const url = `/api/tasks?scope=${isManager ? scope : "mine"}`;
  const { data: tasks, mutate } = useSWR<Task[]>(open ? url : null, fetcher);
  const { data: users } = useSWR<any[]>(open && isManager ? "/api/users" : null, fetcher);

  const { data: counts, mutate: mutateCount } = useSWR<{ count: number }>(
    me ? "/api/tasks?scope=mine&status=pending" : null,
    (u: string) => fetcher<Task[]>(u).then((rows) => ({ count: rows.filter((tk) => tk.status !== "completed" && tk.status !== "cancelled").length })),
    { refreshInterval: 30_000 },
  );
  const openTaskCount = counts?.count ?? 0;

  const [draft, setDraft] = useState({
    title: "", description: "", assigned_to: 0,
    priority: "medium" as Task["priority"], due_date: "",
  });
  const [createMsg, setCreateMsg] = useState("");

  async function addTask(e: React.FormEvent) {
    e.preventDefault();
    setCreateMsg("");
    try {
      await api.post("/api/tasks", {
        title: draft.title,
        description: draft.description || null,
        assigned_to: draft.assigned_to || null,
        priority: draft.priority,
        due_date: draft.due_date || null,
      });
      setDraft({ title: "", description: "", assigned_to: 0, priority: "medium", due_date: "" });
      mutate();
      mutateCount();
    } catch (e: any) { setCreateMsg(e.message); }
  }

  async function setStatus(tk: Task, status: Task["status"]) {
    try {
      await api.patch(`/api/tasks/${tk.id}`, { status });
      mutate();
      mutateCount();
    } catch (e: any) { alert(e.message); }
  }

  async function del(tk: Task) {
    if (!confirm(t("tasks.deleteConfirm", { title: tk.title }))) return;
    try {
      await api.del(`/api/tasks/${tk.id}`);
      mutate();
      mutateCount();
    } catch (e: any) { alert(e.message); }
  }

  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-30 bg-brand-500 hover:bg-brand-600 text-white rounded-full shadow-lg w-14 h-14 flex items-center justify-center"
        title={t("tasks.openButton")}
        aria-label={t("tasks.openButton")}
      >
        <span className="text-2xl leading-none">✓</span>
        {openTaskCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-600 text-white text-xs font-semibold rounded-full w-6 h-6 flex items-center justify-center border-2 border-white">
            {openTaskCount > 99 ? "99+" : openTaskCount}
          </span>
        )}
      </button>

      <div
        className={`fixed inset-0 z-40 transition-opacity ${open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
        onClick={() => setOpen(false)}
      >
        <div className="absolute inset-0 bg-black/30" />
        <aside
          className={`absolute top-0 right-0 h-full w-full max-w-md bg-white shadow-2xl flex flex-col transition-transform duration-200 ${open ? "translate-x-0" : "translate-x-full"}`}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">{t("tasks.heading")}</h2>
              <div className="text-xs text-slate-500">
                {isManager ? t("tasks.subtitleManager") : t("tasks.subtitleUser")}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-slate-500 hover:text-slate-900 text-xl leading-none w-8 h-8 flex items-center justify-center"
              aria-label={t("common.close")}
            >
              ×
            </button>
          </div>

          {isManager && (
            <div className="px-5 py-2 border-b border-slate-200 flex gap-2">
              <button
                onClick={() => setScope("mine")}
                className={`text-xs px-2 py-1 rounded ${scope === "mine" ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-700"}`}
              >{t("tasks.mine")}</button>
              <button
                onClick={() => setScope("all")}
                className={`text-xs px-2 py-1 rounded ${scope === "all" ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-700"}`}
              >{t("tasks.all")}</button>
            </div>
          )}

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
            {tasks?.length === 0 && (
              <div className="text-sm text-slate-500 text-center py-8">{t("tasks.empty")}</div>
            )}
            {tasks?.map((tk) => (
              <div key={tk.id} className="border border-slate-200 rounded p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className={`font-medium text-sm ${tk.status === "completed" ? "line-through text-slate-500" : "text-slate-900"}`}>
                      {tk.title}
                    </div>
                    {tk.description && (
                      <div className="text-xs text-slate-500 mt-1 whitespace-pre-line">{tk.description}</div>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                      <span className={`px-1.5 py-0.5 rounded ${PRIORITY_BADGE[tk.priority]}`}>{t(`tasks.priority.${tk.priority}`)}</span>
                      <span className={`px-1.5 py-0.5 rounded ${STATUS_BADGE[tk.status]}`}>{t(`tasks.status.${tk.status}`)}</span>
                      {tk.due_date && (
                        <span className="text-slate-500">
                          {t("tasks.due", { date: new Date(tk.due_date).toLocaleDateString() })}
                        </span>
                      )}
                      {isManager && (
                        <span className="text-slate-400">→ {t("tasks.user", { id: tk.assigned_to ?? "—" })}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="mt-2 flex gap-2 flex-wrap">
                  {tk.status !== "completed" && (
                    <button onClick={() => setStatus(tk, "completed")} className="text-xs text-green-700 hover:underline">{t("tasks.done")}</button>
                  )}
                  {tk.status === "pending" && (
                    <button onClick={() => setStatus(tk, "in_progress")} className="text-xs text-blue-700 hover:underline">{t("tasks.start")}</button>
                  )}
                  {tk.status === "completed" && (
                    <button onClick={() => setStatus(tk, "pending")} className="text-xs text-slate-500 hover:underline">{t("tasks.reopen")}</button>
                  )}
                  {(isManager || tk.created_by === me?.id) && (
                    <button onClick={() => del(tk)} className="text-xs text-red-600 hover:underline ml-auto">{t("tasks.delete")}</button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <form onSubmit={addTask} className="px-5 py-4 border-t border-slate-200 space-y-2 bg-slate-50">
            <div>
              <label className="label">{t("tasks.title")}</label>
              <input className="input" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} required />
            </div>
            <div>
              <label className="label">{t("tasks.description")}</label>
              <textarea className="input" rows={2} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label">{t("tasks.priority")}</label>
                <select className="input" value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value as Task["priority"] })}>
                  <option value="low">{t("tasks.priority.low")}</option>
                  <option value="medium">{t("tasks.priority.medium")}</option>
                  <option value="high">{t("tasks.priority.high")}</option>
                  <option value="urgent">{t("tasks.priority.urgent")}</option>
                </select>
              </div>
              <div>
                <label className="label">{t("tasks.dueDate")}</label>
                <input className="input" type="date" value={draft.due_date} onChange={(e) => setDraft({ ...draft, due_date: e.target.value })} />
              </div>
            </div>
            {isManager && (
              <div>
                <label className="label">{t("tasks.assignTo")}</label>
                <select className="input" value={draft.assigned_to} onChange={(e) => setDraft({ ...draft, assigned_to: Number(e.target.value) })}>
                  <option value={0}>{t("tasks.myself")}</option>
                  {users?.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.email})</option>)}
                </select>
              </div>
            )}
            {createMsg && <div className="text-sm text-red-600">{createMsg}</div>}
            <button className="btn btn-primary w-full justify-center">{t("tasks.add")}</button>
          </form>
        </aside>
      </div>
    </>
  );
}
