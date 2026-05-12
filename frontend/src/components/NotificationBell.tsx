"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type N = {
  id: number;
  title: string;
  message: string | null;
  is_read: boolean;
  created_at: string;
};

export default function NotificationBell() {
  const { t } = useT();
  const [open, setOpen] = useState(false);

  const { data: count, mutate: mutateCount } = useSWR<{ count: number }>(
    "/api/notifications/unread-count",
    fetcher,
    { refreshInterval: 20_000 },
  );
  const { data: list, mutate: mutateList } = useSWR<N[]>(
    open ? "/api/notifications?limit=20" : null,
    fetcher,
  );

  async function readOne(n: N) {
    if (!n.is_read) {
      try { await api.post(`/api/notifications/${n.id}/read`); mutateList(); mutateCount(); }
      catch {}
    }
  }
  async function readAll() {
    try { await api.post("/api/notifications/read-all"); mutateList(); mutateCount(); }
    catch {}
  }

  const unread = count?.count ?? 0;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="relative w-9 h-9 flex items-center justify-center rounded-full hover:bg-slate-100 text-slate-700"
        aria-label={t("notif.ariaLabel")}
        title={t("notif.title")}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10 21a2 2 0 0 0 4 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-600 text-white text-[10px] font-semibold rounded-full min-w-[18px] h-[18px] px-1 flex items-center justify-center border-2 border-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-11 z-40 w-80 max-h-96 bg-white border border-slate-200 rounded-lg shadow-xl flex flex-col">
            <div className="px-4 py-2 border-b border-slate-200 flex items-center justify-between">
              <div className="font-semibold text-sm">{t("notif.title")}</div>
              {unread > 0 && (
                <button onClick={readAll} className="text-xs text-brand-600 hover:underline">{t("notif.markAll")}</button>
              )}
            </div>
            <div className="flex-1 overflow-y-auto">
              {(!list || list.length === 0) && (
                <div className="px-4 py-6 text-center text-sm text-slate-500">{t("notif.empty")}</div>
              )}
              {list?.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => readOne(n)}
                  className={`w-full text-left px-4 py-2 border-b border-slate-100 hover:bg-slate-50 ${
                    n.is_read ? "opacity-70" : "bg-blue-50/40"
                  }`}
                >
                  <div className="flex items-start gap-2">
                    {!n.is_read && <span className="inline-block w-2 h-2 mt-1.5 rounded-full bg-brand-500 shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-slate-900 truncate">{n.title}</div>
                      {n.message && <div className="text-xs text-slate-600 mt-0.5 line-clamp-2">{n.message}</div>}
                      <div className="text-[10px] text-slate-400 mt-1">{new Date(n.created_at).toLocaleString()}</div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
