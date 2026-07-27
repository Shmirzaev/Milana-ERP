"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { useDialogs } from "@/components/DialogProvider";

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

type User = { id: number; name: string; email: string };

// Warm-palette priority colors — replace the rainbow Tailwind badges.
const PRIORITY_COLOR: Record<Task["priority"], string> = {
  urgent: "var(--erp-accent)",
  high: "var(--erp-warning)",
  medium: "var(--erp-blue)",
  low: "var(--erp-text-muted)",
};

// Same colors, used for the row checkbox / status accent.
const STATUS_COLOR: Record<Task["status"], string> = {
  pending: "var(--erp-text-muted)",
  in_progress: "var(--erp-warning)",
  completed: "var(--erp-success)",
  cancelled: "var(--erp-border-strong)",
};

export default function TasksDrawer() {
  const { me } = useMe();
  const { t } = useT();
  const dialogs = useDialogs();
  const isManager = can(me, "*", "tasks.manage", "management.approve");

  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const url = `/api/tasks?scope=${isManager ? scope : "mine"}`;
  const { data: tasks, mutate } = useSWR<Task[]>(open ? url : null, fetcher);
  const { data: users } = useSWR<User[]>(open && isManager ? "/api/users" : null, fetcher);

  const { data: counts, mutate: mutateCount } = useSWR<{ count: number }>(
    me ? "/api/tasks?scope=mine&status=pending" : null,
    (u: string) =>
      fetcher<Task[]>(u).then((rows) => ({
        count: rows.filter((tk) => tk.status !== "completed" && tk.status !== "cancelled").length,
      })),
    { refreshInterval: 30_000 },
  );
  const openTaskCount = counts?.count ?? 0;

  const [draft, setDraft] = useState({
    title: "",
    description: "",
    assigned_to: 0,
    priority: "medium" as Task["priority"],
    due_date: "",
  });
  const [createMsg, setCreateMsg] = useState("");

  async function addTask(e: React.FormEvent) {
    e.preventDefault();
    setCreateMsg("");
    try {
      await api.post("/api/tasks", {
        title: draft.title,
        description: draft.description || null,
        assigned_to: draft.assigned_to === 0 ? null : draft.assigned_to,
        priority: draft.priority,
        due_date: draft.due_date || null,
      });
      setDraft({ title: "", description: "", assigned_to: 0, priority: "medium", due_date: "" });
      mutate();
      mutateCount();
    } catch (e: any) {
      setCreateMsg(e.message);
    }
  }

  async function setStatus(tk: Task, status: Task["status"]) {
    try {
      await api.patch(`/api/tasks/${tk.id}`, { status });
      mutate();
      mutateCount();
    } catch (e: any) {
      await dialogs.notify(e.message);
    }
  }

  async function del(tk: Task) {
    if (!(await dialogs.ask({ message: t("tasks.deleteConfirm", { title: tk.title }), tone: "danger" }))) return;
    try {
      await api.del(`/api/tasks/${tk.id}`);
      mutate();
      mutateCount();
    } catch (e: any) {
      await dialogs.notify(e.message);
    }
  }

  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open]);

  return (
    <>
      {/* ============================================================ */}
      {/* FAB — "Ink Coin"                                              */}
      {/* ============================================================ */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={t("tasks.openButton")}
        aria-label={t("tasks.openButton")}
        className="fixed bottom-2 right-2 z-30 grid h-10 w-10 place-items-center transition sm:bottom-6 sm:right-6 sm:h-[60px] sm:w-[60px]"
        style={{
          borderRadius: "50%",
          background: "var(--erp-primary)",
          color: "var(--erp-primary-text)",
          border: "1px solid var(--erp-primary-hover)",
          boxShadow:
            "0 12px 28px -10px var(--erp-shadow-strong), inset 0 -2px 0 rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.06)",
          cursor: "pointer",
        }}
      >
        {/* hairline inner ring */}
        <span
          aria-hidden
          style={{
            position: "absolute",
            inset: 5,
            borderRadius: "50%",
            border: "1px dashed color-mix(in srgb, var(--erp-primary-text) 18%, transparent)",
            pointerEvents: "none",
          }}
        />
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
        </svg>

        {openTaskCount > 0 && (
          <span
            className="absolute"
            style={{
              top: -2,
              right: -2,
              minWidth: 22,
              height: 22,
              padding: "0 6px",
              background: "var(--erp-accent)",
              color: "#fff",
              borderRadius: 11,
              fontSize: 11,
              fontWeight: 700,
              display: "grid",
              placeItems: "center",
              border: "2px solid var(--erp-bg)",
              boxShadow: "0 2px 4px rgba(122,40,6,0.4)",
            }}
          >
            {openTaskCount > 99 ? "99+" : openTaskCount}
          </span>
        )}
      </button>

      {/* ============================================================ */}
      {/* DRAWER — "Ledger" interior                                    */}
      {/* ============================================================ */}
      {open && (
      <div
        className="fixed inset-0 z-40 opacity-100 pointer-events-auto"
        onClick={() => setOpen(false)}
      >
        <div className="absolute inset-0" style={{ background: "color-mix(in srgb, var(--erp-bg) 66%, transparent)" }} />

        <aside
          role="dialog"
          aria-modal="true"
          aria-labelledby="tasks-drawer-title"
          className="absolute top-0 right-0 h-full w-full max-w-md flex flex-col translate-x-0 transition-transform duration-200"
          style={{
            background: "var(--erp-surface)",
            borderLeft: "1px solid var(--erp-border)",
            boxShadow: "-24px 0 60px -16px var(--erp-shadow-strong)",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <header
            className="px-7 pt-6 pb-4"
            style={{ borderBottom: "1px solid var(--erp-border)", position: "relative" }}
          >
            <div className="flex items-start justify-between">
              <div>
                <div
                  className="text-[10.5px] font-semibold uppercase"
                  style={{ letterSpacing: "0.22em", color: "var(--erp-text-muted)" }}
                >
                  {t("tasks.ledgerEyebrow")}
                </div>
                <h2
                  id="tasks-drawer-title"
                  className="m-0 mt-1.5 leading-none"
                  style={{
                    fontFamily:
                      "'Instrument Serif', 'Iowan Old Style', Palatino, serif",
                    fontWeight: 400,
                    fontSize: 34,
                    letterSpacing: "-0.01em",
                    color: "var(--erp-text)",
                  }}
                >
                  {t("tasks.heading")}
                </h2>
                <p className="m-0 mt-2 text-[12.5px]" style={{ color: "var(--erp-text-soft)" }}>
                  {isManager ? t("tasks.subtitleManager") : t("tasks.subtitleUser")}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t("common.close")}
                className="grid place-items-center rounded-md transition"
                style={{
                  width: 32,
                  height: 32,
                  border: "none",
                  background: "transparent",
                  color: "var(--erp-text-soft)",
                  cursor: "pointer",
                }}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                >
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Tabs (manager only) — text + underline, no pill buttons */}
            {isManager && (
              <div
                className="flex gap-5 mt-4"
                style={{ marginBottom: -17 }}
              >
                {(["mine", "all"] as const).map((s) => {
                  const active = scope === s;
                  return (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setScope(s)}
                      className="pb-3 pt-2"
                      style={{
                        background: "transparent",
                        border: "none",
                        padding: "8px 0 12px",
                        borderBottom: active
                          ? "2px solid var(--erp-primary)"
                          : "2px solid transparent",
                        fontSize: 13,
                        fontWeight: active ? 600 : 500,
                        color: active ? "var(--erp-text)" : "var(--erp-text-muted)",
                        cursor: "pointer",
                      }}
                    >
                      {t(s === "mine" ? "tasks.mine" : "tasks.all")}
                    </button>
                  );
                })}
              </div>
            )}
          </header>

          {/* Ledger body */}
          <div className="flex-1 overflow-y-auto" style={{ position: "relative" }}>
            {/* hairline ruling background */}
            <div
              aria-hidden
              style={{
                position: "absolute",
                inset: 0,
                backgroundImage:
                  "repeating-linear-gradient(to bottom, transparent 0, transparent 71px, var(--erp-surface-muted) 71px, var(--erp-surface-muted) 72px)",
                pointerEvents: "none",
              }}
            />

            {tasks && tasks.length === 0 && <EmptyState t={t} />}

            {tasks?.map((tk, i) => (
              <LedgerRow
                key={tk.id}
                row={i + 1}
                task={tk}
                isManager={isManager}
                users={users}
                me={me}
                t={t}
                setStatus={setStatus}
                del={del}
              />
            ))}
          </div>

          {/* New entry form */}
          <form
            onSubmit={addTask}
            className="px-7 pt-4 pb-5"
            style={{
              borderTop: "2px solid var(--erp-primary)",
              background: "var(--erp-surface-muted)",
            }}
          >
            <div
              className="flex items-center gap-2 mb-2.5"
              style={{
                fontSize: 10.5,
                letterSpacing: "0.22em",
                textTransform: "uppercase",
                color: "var(--erp-text-muted)",
                fontWeight: 600,
              }}
            >
              <span className="mono" style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
                {String((tasks?.length ?? 0) + 1).padStart(3, "0")}
              </span>
              <span>{t("tasks.newEntry")}</span>
            </div>

            <input
              className="input mb-2"
              placeholder={t("tasks.title")}
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              required
            />

            <textarea
              className="input mb-2"
              rows={2}
              placeholder={t("tasks.description")}
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              style={{ resize: "none" }}
            />

            <div
              className="grid gap-2 mb-3"
              style={{ gridTemplateColumns: isManager ? "repeat(auto-fit, minmax(8.25rem, 1fr))" : "repeat(2, minmax(0, 1fr))" }}
            >
              <select
                className="input"
                value={draft.priority}
                onChange={(e) =>
                  setDraft({ ...draft, priority: e.target.value as Task["priority"] })
                }
              >
                <option value="low">{t("tasks.priority.low")}</option>
                <option value="medium">{t("tasks.priority.medium")}</option>
                <option value="high">{t("tasks.priority.high")}</option>
                <option value="urgent">{t("tasks.priority.urgent")}</option>
              </select>
              <input
                className="input"
                type="date"
                value={draft.due_date}
                onChange={(e) => setDraft({ ...draft, due_date: e.target.value })}
              />
              {isManager && (
                <select
                  className="input"
                  value={draft.assigned_to}
                  onChange={(e) =>
                    setDraft({ ...draft, assigned_to: Number(e.target.value) })
                  }
                >
                  <option value={0}>{t("tasks.myself")}</option>
                  <option value={-1}>{t("tasks.everyone")}</option>
                  {users?.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {createMsg && (
              <div
                className="mb-2 text-[12.5px] px-3 py-2 rounded-md"
                style={{
                  background: "var(--erp-danger-soft)",
                  color: "var(--erp-danger)",
                  border: "1px solid color-mix(in srgb, var(--erp-danger) 35%, var(--erp-danger-soft))",
                }}
              >
                {createMsg}
              </div>
            )}

            <button type="submit" className="btn btn-primary w-full justify-center" style={{ height: 40 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M12 5v14M5 12h14" />
              </svg>
              {t("tasks.add")}
            </button>
          </form>
        </aside>
      </div>
      )}
    </>
  );
}

// ============================================================================
// LEDGER ROW
// ============================================================================
function LedgerRow({
  row,
  task,
  isManager,
  users,
  me,
  t,
  setStatus,
  del,
}: {
  row: number;
  task: Task;
  isManager: boolean;
  users: User[] | undefined;
  me: any;
  t: (k: string, vars?: any) => string;
  setStatus: (tk: Task, s: Task["status"]) => void;
  del: (tk: Task) => void;
}) {
  const done = task.status === "completed";
  const inProgress = task.status === "in_progress";
  const priColor = PRIORITY_COLOR[task.priority];
  const stColor = STATUS_COLOR[task.status];

  const assigneeName =
    task.assigned_to == null
      ? null
      : users?.find((u) => u.id === task.assigned_to)?.name ??
        (task.assigned_to === me?.id ? t("tasks.myself") : `#${task.assigned_to}`);

  function onToggleDone() {
    setStatus(task, done ? "pending" : "completed");
  }

  return (
    <div
      style={{
        position: "relative",
        padding: "14px 26px 14px 56px",
        minHeight: 72,
        borderBottom: "1px solid transparent",
      }}
    >
      {/* row number */}
      <div
        className="mono"
        style={{
          position: "absolute",
          left: 16,
          top: 18,
          fontSize: 11,
          color: "var(--erp-text-muted)",
          letterSpacing: "0.04em",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        }}
      >
        {String(row).padStart(3, "0")}
      </div>

      {/* checkbox circle */}
      <button
        type="button"
        onClick={onToggleDone}
        aria-label={done ? t("tasks.reopen") : t("tasks.done")}
        style={{
          position: "absolute",
          left: 32,
          top: 18,
          width: 18,
          height: 18,
          borderRadius: "50%",
          border: "1.5px solid " + (done ? stColor : "var(--erp-border-strong)"),
          background: done ? stColor : "transparent",
          cursor: "pointer",
          padding: 0,
          display: "grid",
          placeItems: "center",
        }}
      >
        {done && (
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3">
            <path d="M5 12l5 5L20 7" />
          </svg>
        )}
      </button>

      {/* title */}
      <div
        style={{
          fontSize: 13.5,
          fontWeight: 500,
          color: done ? "var(--erp-text-muted)" : "var(--erp-text)",
          textDecoration: done ? "line-through" : "none",
          marginBottom: 4,
          lineHeight: 1.35,
        }}
      >
        {task.title}
      </div>

      {task.description && (
        <div
          style={{
            fontSize: 12,
            color: "var(--erp-text-soft)",
            lineHeight: 1.45,
            marginBottom: 6,
            whiteSpace: "pre-line",
          }}
        >
          {task.description}
        </div>
      )}

      {/* meta row */}
      <div
        className="flex items-center gap-2 flex-wrap"
        style={{ fontSize: 11, color: "var(--erp-text-muted)" }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            color: priColor,
            fontWeight: 600,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: "currentColor" }} />
          {t(`tasks.priority.${task.priority}`)}
        </span>

        {task.due_date && (
          <>
            <span style={{ color: "var(--erp-border-strong)" }}>·</span>
            <span style={{ letterSpacing: "0.04em" }}>
              {new Date(task.due_date).toLocaleDateString()}
            </span>
          </>
        )}

        {assigneeName && (
          <>
            <span style={{ color: "var(--erp-border-strong)" }}>·</span>
            <span>{assigneeName}</span>
          </>
        )}

        {inProgress && (
          <>
            <span style={{ color: "var(--erp-border-strong)" }}>·</span>
            <span style={{ color: "var(--erp-warning)", fontWeight: 600 }}>
              {t("tasks.status.in_progress")}
            </span>
          </>
        )}

        {/* spacer */}
        <span style={{ flex: 1 }} />

        {/* row actions */}
        {task.status === "pending" && (
          <button
            type="button"
            onClick={() => setStatus(task, "in_progress")}
            className="text-[11px] hover:underline"
            style={{ color: "var(--erp-blue)", background: "transparent", border: "none", cursor: "pointer", padding: 0 }}
          >
            {t("tasks.start")}
          </button>
        )}
        {(isManager || task.created_by === me?.id) && (
          <button
            type="button"
            onClick={() => del(task)}
            className="text-[11px] hover:underline"
            style={{ color: "var(--erp-danger)", background: "transparent", border: "none", cursor: "pointer", padding: 0 }}
          >
            {t("tasks.delete")}
          </button>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// EMPTY STATE — sealed blank page
// ============================================================================
function EmptyState({ t }: { t: (k: string) => string }) {
  return (
    <div
      className="flex items-center justify-center text-center"
      style={{ minHeight: 320, padding: 32, position: "relative" }}
    >
      <div style={{ position: "relative", maxWidth: 280 }}>
        <svg width="68" height="68" viewBox="0 0 68 68" style={{ marginBottom: 18 }} aria-hidden>
          <circle cx="34" cy="34" r="32" fill="none" stroke="var(--erp-accent)" strokeWidth="1" strokeDasharray="2 3" opacity="0.5" />
          <circle cx="34" cy="34" r="22" fill="var(--erp-surface-muted)" stroke="var(--erp-border-strong)" />
          <text
            x="34"
            y="41"
            textAnchor="middle"
            fontFamily="'Instrument Serif', serif"
            fontSize="22"
            fill="var(--erp-text-muted)"
            fontStyle="italic"
          >
            ∅
          </text>
        </svg>
        <div
          style={{
            fontFamily: "'Instrument Serif', 'Iowan Old Style', Palatino, serif",
            fontWeight: 400,
            fontSize: 22,
            lineHeight: 1.2,
            marginBottom: 8,
            color: "var(--erp-text)",
          }}
        >
          {t("tasks.emptyTitle")}
        </div>
        <p style={{ fontSize: 13, color: "var(--erp-text-soft)", margin: 0, lineHeight: 1.5 }}>
          {t("tasks.emptyHint")}
        </p>
      </div>
    </div>
  );
}
