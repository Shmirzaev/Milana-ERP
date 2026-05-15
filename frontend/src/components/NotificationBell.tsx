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

/**
 * NotificationBell — "Live Ping" variant.
 * Minimal bell glyph, terracotta dot + soft pulsing ring when there is unread.
 * Dropdown panel restyled to the warm Milana palette.
 */
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
      try {
        await api.post(`/api/notifications/${n.id}/read`);
        mutateList();
        mutateCount();
      } catch {}
    }
  }

  async function readAll() {
    try {
      await api.post("/api/notifications/read-all");
      mutateList();
      mutateCount();
    } catch {}
  }

  const unread = count?.count ?? 0;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="relative w-9 h-9 grid place-items-center rounded-md text-[#56503f] transition hover:bg-[#f1efe8] hover:text-[#14110b]"
        aria-label={t("notif.ariaLabel")}
        title={t("notif.title")}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="w-[18px] h-[18px]"
        >
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10 21a2 2 0 0 0 4 0" />
        </svg>

        {/* live-ping indicator — only when unread */}
        {unread > 0 && (
          <>
            {/* solid dot */}
            <span
              className="absolute"
              style={{
                top: 8,
                right: 9,
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: "#c2410c",
                boxShadow: "0 0 0 2px #fdfcf8",
              }}
              aria-hidden
            />
            {/* pulsing ring (CSS keyframe in globals.css: mil-ping) */}
            <span
              className="absolute pointer-events-none"
              style={{
                top: 5,
                right: 6,
                width: 13,
                height: 13,
                borderRadius: "50%",
                background: "#c2410c",
                opacity: 0.5,
                animation: "mil-ping 1.8s ease-out infinite",
              }}
              aria-hidden
            />
          </>
        )}
      </button>

      {open && (
        <>
          {/* click-outside layer */}
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 top-11 z-40 w-80 max-h-96 rounded-lg shadow-xl flex flex-col"
            style={{
              background: "#fdfcf8",
              border: "1px solid #e3dfd3",
              boxShadow:
                "0 20px 40px -16px rgba(20,17,11,0.18), 0 2px 4px rgba(20,17,11,0.06)",
            }}
          >
            <div className="px-4 py-2.5 flex items-center justify-between border-b border-[#e3dfd3]">
              <div className="flex items-center gap-2">
                <span className="text-[10.5px] font-semibold tracking-[0.18em] uppercase text-[#8a8472]">
                  {t("notif.title")}
                </span>
                {unread > 0 && (
                  <span
                    className="inline-flex items-center justify-center font-mono text-[10px] font-semibold"
                    style={{
                      minWidth: 18,
                      height: 18,
                      padding: "0 5px",
                      background: "#fbe9dd",
                      color: "#9a3308",
                      borderRadius: 9,
                    }}
                  >
                    {unread > 99 ? "99+" : unread}
                  </span>
                )}
              </div>
              {unread > 0 && (
                <button
                  onClick={readAll}
                  className="text-[11.5px] font-medium text-[#c2410c] hover:underline"
                >
                  {t("notif.markAll")}
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto">
              {(!list || list.length === 0) && (
                <div className="px-4 py-8 text-center text-[13px] text-[#8a8472]">
                  {t("notif.empty")}
                </div>
              )}
              {list?.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => readOne(n)}
                  className="w-full text-left px-4 py-3 border-b border-[#ecebe3] transition hover:bg-[#fdf3eb]"
                  style={{
                    background: n.is_read ? "transparent" : "rgba(251,233,221,0.45)",
                  }}
                >
                  <div className="flex items-start gap-2.5">
                    {!n.is_read && (
                      <span
                        className="inline-block shrink-0"
                        style={{
                          width: 6,
                          height: 6,
                          marginTop: 7,
                          borderRadius: "50%",
                          background: "#c2410c",
                        }}
                      />
                    )}
                    {n.is_read && <span className="w-1.5 shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <div
                        className={`text-[13px] font-medium truncate ${
                          n.is_read ? "text-[#56503f]" : "text-[#14110b]"
                        }`}
                      >
                        {n.title}
                      </div>
                      {n.message && (
                        <div className="text-[11.5px] text-[#56503f] mt-0.5 line-clamp-2">
                          {n.message}
                        </div>
                      )}
                      <div className="text-[10px] tracking-wider text-[#8a8472] mt-1.5 font-mono">
                        {new Date(n.created_at).toLocaleString()}
                      </div>
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
