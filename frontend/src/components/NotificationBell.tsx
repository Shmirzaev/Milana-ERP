"use client";
import { createPortal } from "react-dom";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { BellRing, Play, Volume2, VolumeX } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type N = {
  id: number;
  title: string;
  message: string | null;
  link: string | null;
  is_read: boolean;
  created_at: string;
};

type BrowserNotificationPermission = NotificationPermission | "unsupported";
type AudioWindow = Window & typeof globalThis & { webkitAudioContext?: typeof AudioContext };
type AlertSound = "ding" | "chime" | "bell" | "alert";

const ALERTS_ENABLED_KEY = "milana_notification_alerts_enabled";
const LAST_ALERTED_ID_KEY = "milana_notification_last_alerted_id";
const ALERT_SOUND_KEY = "milana_notification_sound";
const ALERT_VOLUME_KEY = "milana_notification_volume";
const ALERT_ICON = "/branding/font_A_inter.png";
const DEFAULT_ALERT_VOLUME = 0.9;
const SOUND_OPTIONS: Array<{ value: AlertSound; labelKey: string }> = [
  { value: "ding", labelKey: "notif.sound.ding" },
  { value: "chime", labelKey: "notif.sound.chime" },
  { value: "bell", labelKey: "notif.sound.bell" },
  { value: "alert", labelKey: "notif.sound.alert" },
];

function clampVolume(value: number) {
  if (!Number.isFinite(value)) return DEFAULT_ALERT_VOLUME;
  return Math.max(0.2, Math.min(1, value));
}

function isAlertSound(value: string | null): value is AlertSound {
  return SOUND_OPTIONS.some((option) => option.value === value);
}

/**
 * Fallback link derivation for notifications created before the backend
 * started storing a `link` per row. Pattern-matches the title/message to
 * route the user to the page where they should act.
 *
 * Order matters: more specific patterns first.
 */
function deriveLink(n: N): string | null {
  if (n.link) return n.link;
  const hay = `${n.title} ${n.message ?? ""}`;

  // Bundle: "Bundle BND-... sent/received"
  const bundleMatch = hay.match(/\bBND[-_][A-Z0-9-]+/i);
  if (bundleMatch && /\bbundle\b/i.test(hay)) {
    if (/printing/i.test(hay)) return "/bundles/scan/printing";
    if (/sewing/i.test(hay)) return "/bundles/scan/sewing";
    if (/cutting/i.test(hay)) return "/bundles/scan/cutting";
    return "/bundles/scan";
  }

  // Package: "Package PKG-..."
  const packageMatch = hay.match(/\bPKG[-_][A-Z0-9-]+/i);
  if (packageMatch && /\bpackage\b/i.test(hay)) return "/packages/scan";

  // Sales order: "Sales order SO-..." / "for SO-..." / "approved for SO-..."
  const soMatch = hay.match(/\bSO[-_]\d+[-_]?\d*/i);
  if (soMatch) {
    if (/sent to planning|estimate approved|planning/i.test(hay)) return "/planning";
    if (/estimate ready|approve/i.test(hay)) return "/sales-orders";
    return "/sales-orders";
  }

  // Work order: "WO #123" or "work order #123"
  const woMatch = hay.match(/\bWO\s*#?(\d+)|\bwork order\s*#?(\d+)/i);
  if (woMatch) {
    const wid = woMatch[1] || woMatch[2];
    if (/sewing/i.test(hay)) return `/work-orders/${wid}/sewing`;
    if (/printing/i.test(hay)) return `/work-orders/${wid}/printing`;
    if (/cutting/i.test(hay)) return `/work-orders/${wid}/cutting`;
    if (/packaging|packed/i.test(hay)) return `/work-orders/${wid}/packaging`;
    return `/work-orders/${wid}`;
  }

  // Generic department-style messages
  if (/awaiting packaging|packed goods|ready for storage/i.test(hay)) return "/packages";
  if (/incoming cutting/i.test(hay)) return "/bundles/scan/printing";
  if (/printed pieces/i.test(hay)) return "/bundles/scan/sewing";
  if (/shipment.*delivered|invoice/i.test(hay)) return "/finance";

  return null;
}

/**
 * NotificationBell — "Live Ping" variant.
 * Minimal bell glyph, terracotta dot + soft pulsing ring when there is unread.
 * Dropdown panel restyled to the warm Milana palette.
 */
export default function NotificationBell() {
  const { t } = useT();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const bellRef = useRef<HTMLButtonElement | null>(null);
  const [panelPosition, setPanelPosition] = useState<{
    left: number;
    top: number;
    width: number;
    maxHeight: number;
  } | null>(null);
  const [alertsEnabled, setAlertsEnabled] = useState(false);
  const [permission, setPermission] = useState<BrowserNotificationPermission>("default");
  const [alertSound, setAlertSound] = useState<AlertSound>("chime");
  const [alertVolume, setAlertVolume] = useState(DEFAULT_ALERT_VOLUME);
  const audioContextRef = useRef<AudioContext | null>(null);
  const notificationRegistrationRef = useRef<ServiceWorkerRegistration | null>(null);
  const initializedAlertsRef = useRef(false);
  const lastAlertedIdRef = useRef(0);
  const alertsActive = alertsEnabled && permission === "granted";

  const { data: summary, mutate: mutateCount } = useSWR<{ count: number; rows: N[] }>(
    "/api/notifications/summary?limit=10",
    fetcher,
    {
      refreshInterval: alertsActive ? 15_000 : 60_000,
      refreshWhenHidden: alertsActive,
      refreshWhenOffline: false,
      revalidateOnFocus: true,
    },
  );
  const { data: list, mutate: mutateList } = useSWR<N[]>(
    open ? "/api/notifications?limit=20" : null,
    fetcher,
  );
  const alertList = alertsActive ? summary?.rows : undefined;

  useEffect(() => {
    if (typeof window === "undefined") return;
    setAlertsEnabled(localStorage.getItem(ALERTS_ENABLED_KEY) === "1");
    const savedSound = localStorage.getItem(ALERT_SOUND_KEY);
    if (isAlertSound(savedSound)) setAlertSound(savedSound);
    const savedVolume = Number(localStorage.getItem(ALERT_VOLUME_KEY));
    if (Number.isFinite(savedVolume)) setAlertVolume(clampVolume(savedVolume));
    const rawLastId = Number(localStorage.getItem(LAST_ALERTED_ID_KEY) || "0");
    lastAlertedIdRef.current = Number.isFinite(rawLastId) ? rawLastId : 0;
    setPermission("Notification" in window ? window.Notification.permission : "unsupported");
  }, []);

  const getAudioContext = useCallback(() => {
    if (typeof window === "undefined") return null;
    if (audioContextRef.current) return audioContextRef.current;
    const audioWindow = window as AudioWindow;
    const AudioCtor = audioWindow.AudioContext || audioWindow.webkitAudioContext;
    if (!AudioCtor) return null;
    audioContextRef.current = new AudioCtor();
    return audioContextRef.current;
  }, []);

  const primeNotificationAudio = useCallback(async () => {
    try {
      const ctx = getAudioContext();
      if (ctx?.state === "suspended") await ctx.resume();
    } catch {}
  }, [getAudioContext]);

  const playTone = useCallback((
    ctx: AudioContext,
    frequency: number,
    offset: number,
    duration: number,
    type: OscillatorType = "triangle",
    gainScale = 1,
  ) => {
    const startedAt = ctx.currentTime + offset;
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    const peak = Math.max(0.001, Math.min(0.34, alertVolume * 0.34 * gainScale));

    oscillator.type = type;
    oscillator.frequency.setValueAtTime(frequency, startedAt);
    gain.gain.setValueAtTime(0.0001, startedAt);
    gain.gain.exponentialRampToValueAtTime(peak, startedAt + 0.018);
    gain.gain.exponentialRampToValueAtTime(0.0001, startedAt + duration);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start(startedAt);
    oscillator.stop(startedAt + duration + 0.02);
  }, [alertVolume]);

  const playNotificationSound = useCallback(async () => {
    try {
      const ctx = getAudioContext();
      if (!ctx) return;
      if (ctx.state === "suspended") await ctx.resume();

      if (alertSound === "ding") {
        playTone(ctx, 880, 0.01, 0.18, "sine");
        playTone(ctx, 1175, 0.12, 0.2, "sine", 0.72);
      } else if (alertSound === "bell") {
        playTone(ctx, 988, 0.01, 0.42, "triangle");
        playTone(ctx, 1319, 0.04, 0.36, "sine", 0.46);
      } else if (alertSound === "alert") {
        playTone(ctx, 740, 0.01, 0.16, "square", 0.62);
        playTone(ctx, 740, 0.22, 0.16, "square", 0.62);
      } else {
        playTone(ctx, 659, 0.01, 0.18, "triangle", 0.78);
        playTone(ctx, 880, 0.12, 0.2, "triangle");
        playTone(ctx, 1175, 0.25, 0.22, "sine", 0.74);
      }
    } catch {}
  }, [alertSound, getAudioContext, playTone]);

  const getNotificationRegistration = useCallback(async () => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return null;
    if (notificationRegistrationRef.current) return notificationRegistrationRef.current;
    try {
      const existing = await navigator.serviceWorker.getRegistration("/");
      const registration = existing || await navigator.serviceWorker.register("/notification-sw.js");
      notificationRegistrationRef.current = registration;
      return await navigator.serviceWorker.ready;
    } catch {
      return null;
    }
  }, []);

  const showDesktopNotification = useCallback(async (title: string, body: string, notification: N) => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    if (window.Notification.permission !== "granted") return;

    try {
      const dest = deriveLink(notification);
      const options: NotificationOptions = {
        body,
        icon: ALERT_ICON,
        badge: ALERT_ICON,
        tag: `milana-notification-${notification.id}`,
        data: dest ? { url: dest } : undefined,
        silent: false,
      };
      const registration = await getNotificationRegistration();
      if (registration?.showNotification) {
        await registration.showNotification(title, options);
        return;
      }

      const notice = new window.Notification(title, options);
      notice.onclick = () => {
        window.focus();
        if (dest) router.push(dest);
        notice.close();
      };
    } catch {}
  }, [getNotificationRegistration, router]);

  async function enableAlerts() {
    if (typeof window === "undefined" || !("Notification" in window)) {
      setPermission("unsupported");
      return;
    }

    const nextPermission =
      window.Notification.permission === "default"
        ? await window.Notification.requestPermission()
        : window.Notification.permission;
    setPermission(nextPermission);

    if (nextPermission === "granted") {
      localStorage.setItem(ALERTS_ENABLED_KEY, "1");
      setAlertsEnabled(true);
      await primeNotificationAudio();
      void getNotificationRegistration();
    }
  }

  async function testAlerts() {
    await enableAlerts();
    if (typeof window !== "undefined" && "Notification" in window && window.Notification.permission === "granted") {
      const testNotification: N = {
        id: Date.now(),
        title: t("notif.testTitle"),
        message: t("notif.testBody"),
        link: null,
        is_read: false,
        created_at: new Date().toISOString(),
      };
      await showDesktopNotification(testNotification.title, testNotification.message || "", testNotification);
    }
    await playNotificationSound();
  }

  function changeAlertSound(value: string) {
    if (!isAlertSound(value)) return;
    setAlertSound(value);
    if (typeof window !== "undefined") localStorage.setItem(ALERT_SOUND_KEY, value);
    void playNotificationSound();
  }

  function changeAlertVolume(value: number) {
    const nextVolume = clampVolume(value);
    setAlertVolume(nextVolume);
    if (typeof window !== "undefined") localStorage.setItem(ALERT_VOLUME_KEY, String(nextVolume));
  }

  useEffect(() => {
    if (!alertsActive || typeof window === "undefined") return;
    const prime = () => {
      void primeNotificationAudio();
    };
    window.addEventListener("pointerdown", prime, { once: true });
    window.addEventListener("keydown", prime, { once: true });
    return () => {
      window.removeEventListener("pointerdown", prime);
      window.removeEventListener("keydown", prime);
    };
  }, [alertsActive, primeNotificationAudio]);

  useEffect(() => {
    if (!alertsActive || !alertList) return;

    if (!initializedAlertsRef.current) {
      initializedAlertsRef.current = true;
      if (lastAlertedIdRef.current <= 0 && alertList.length > 0) {
        const maxSeenId = Math.max(...alertList.map((n) => n.id));
        lastAlertedIdRef.current = maxSeenId;
        localStorage.setItem(LAST_ALERTED_ID_KEY, String(maxSeenId));
        return;
      }
    }
    if (!alertList.length) return;

    const fresh = alertList
      .filter((n) => !n.is_read && n.id > lastAlertedIdRef.current)
      .sort((a, b) => a.id - b.id);
    if (!fresh.length) return;

    const latest = fresh[fresh.length - 1];
    if (fresh.length === 1) {
      void showDesktopNotification(latest.title, latest.message || t("notif.title"), latest);
    } else {
      void showDesktopNotification(
        t("notif.newMany", { count: fresh.length }),
        t("notif.latestPrefix", { title: latest.title }),
        latest,
      );
    }
    void playNotificationSound();

    lastAlertedIdRef.current = Math.max(lastAlertedIdRef.current, ...fresh.map((n) => n.id));
    localStorage.setItem(LAST_ALERTED_ID_KEY, String(lastAlertedIdRef.current));
  }, [alertList, alertsActive, playNotificationSound, showDesktopNotification, t]);

  async function readOne(n: N) {
    // Mark-as-read in the background; don't block navigation on the request.
    if (!n.is_read) {
      api.post(`/api/notifications/${n.id}/read`)
        .then(() => { mutateList(); mutateCount(); })
        .catch(() => {});
    }
    // Navigate to the place this notification is about.
    const dest = deriveLink(n);
    if (dest) {
      setOpen(false);
      router.push(dest);
    }
  }

  async function readAll() {
    try {
      await api.post("/api/notifications/read-all");
      mutateList();
      mutateCount();
    } catch {}
  }

  const unread = summary?.count ?? 0;
  const canEnableAlerts = permission === "default" || permission === "granted";

  const updatePanelPosition = useCallback(() => {
    const bell = bellRef.current;
    if (!bell) return;

    const rect = bell.getBoundingClientRect();
    const viewport = window.visualViewport;
    const viewportLeft = viewport?.offsetLeft ?? 0;
    const viewportTop = viewport?.offsetTop ?? 0;
    const viewportWidth = viewport?.width ?? window.innerWidth;
    const viewportHeight = viewport?.height ?? window.innerHeight;
    const viewportRight = viewportLeft + viewportWidth;
    const viewportBottom = viewportTop + viewportHeight;
    const gutter = 8;
    const gap = 8;
    const width = Math.max(0, Math.min(320, viewportWidth - gutter * 2));
    const roomBelow = viewportBottom - rect.bottom - gap - gutter;
    const roomAbove = rect.top - viewportTop - gap - gutter;
    const openAbove = roomBelow < 192 && roomAbove > roomBelow;
    const maxHeight = Math.max(0, Math.min(384, openAbove ? roomAbove : roomBelow));
    const left = Math.max(
      viewportLeft + gutter,
      Math.min(rect.right - width, viewportRight - width - gutter),
    );

    setPanelPosition({
      left,
      top: openAbove ? rect.top - gap - maxHeight : rect.bottom + gap,
      width,
      maxHeight,
    });
  }, []);

  useEffect(() => {
    if (!open) {
      setPanelPosition(null);
      return;
    }

    updatePanelPosition();
    const viewport = window.visualViewport;
    window.addEventListener("resize", updatePanelPosition);
    window.addEventListener("scroll", updatePanelPosition, true);
    viewport?.addEventListener("resize", updatePanelPosition);
    viewport?.addEventListener("scroll", updatePanelPosition);
    return () => {
      window.removeEventListener("resize", updatePanelPosition);
      window.removeEventListener("scroll", updatePanelPosition, true);
      viewport?.removeEventListener("resize", updatePanelPosition);
      viewport?.removeEventListener("scroll", updatePanelPosition);
    };
  }, [open, updatePanelPosition]);

  return (
    <div className="relative">
      <button
        ref={bellRef}
        type="button"
        onClick={() => {
          setOpen(!open);
          if (alertsEnabled) void primeNotificationAudio();
        }}
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
                background: "var(--erp-accent)",
                boxShadow: "0 0 0 2px var(--erp-surface)",
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
                background: "var(--erp-accent)",
                opacity: 0.5,
                animation: "mil-ping 1.8s ease-out infinite",
              }}
              aria-hidden
            />
          </>
        )}
      </button>

      {open && panelPosition && createPortal((
        <>
          {/* click-outside layer */}
          <div className="fixed inset-0 z-[90]" onClick={() => setOpen(false)} />
          <div
            role="dialog"
            aria-label={t("notif.title")}
            className="fixed z-[100] flex flex-col overflow-y-auto overscroll-contain rounded-lg shadow-lg"
            style={{
              ...panelPosition,
              background: "var(--erp-surface)",
              border: "1px solid var(--erp-border)",
              boxShadow:
                "0 20px 40px -16px var(--erp-shadow-strong), 0 2px 4px var(--erp-shadow)",
            }}
          >
            <div className="flex shrink-0 items-center justify-between border-b border-[#e3dfd3] px-4 py-2.5">
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
                      background: "var(--erp-accent-soft)",
                      color: "var(--erp-accent)",
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

            <div className="shrink-0 border-b border-[#e3dfd3] px-3 py-2">
              {permission === "unsupported" && (
                <div className="flex items-center gap-2 rounded-md bg-[#f8f6ef] px-2.5 py-2 text-[11.5px] text-[#8a8472]">
                  <VolumeX className="h-3.5 w-3.5 shrink-0" />
                  <span>{t("notif.alertsUnsupported")}</span>
                </div>
              )}
              {permission === "denied" && (
                <div className="flex items-center gap-2 rounded-md bg-[#fff7ed] px-2.5 py-2 text-[11.5px] text-[#9a3412]">
                  <VolumeX className="h-3.5 w-3.5 shrink-0" />
                  <span>{t("notif.alertsBlocked")}</span>
                </div>
              )}
              {canEnableAlerts && (
                <button
                  type="button"
                  onClick={enableAlerts}
                  className="flex w-full items-center justify-between gap-3 rounded-md border border-[#e3dfd3] bg-[#fdfcf8] px-2.5 py-2 text-left transition hover:border-[#d4cabc] hover:bg-[#f8f6ef]"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    {alertsActive ? (
                      <Volume2 className="h-3.5 w-3.5 shrink-0 text-[#15803d]" />
                    ) : (
                      <BellRing className="h-3.5 w-3.5 shrink-0 text-[#c2410c]" />
                    )}
                    <span className="min-w-0">
                      <span className="block break-words text-[12px] font-medium text-[#2c2920]">
                        {alertsActive ? t("notif.alertsEnabled") : t("notif.enableAlerts")}
                      </span>
                      <span className="block break-words text-[10.5px] text-[#8a8472]">
                        {t("notif.alertsHint")}
                      </span>
                    </span>
                  </span>
                </button>
              )}
              {alertsActive && (
                <div className="mt-2 space-y-2">
                  <div className="grid grid-cols-[1fr_36px] gap-2">
                    <label className="sr-only" htmlFor="notification-sound">
                      {t("notif.soundLabel")}
                    </label>
                    <select
                      id="notification-sound"
                      value={alertSound}
                      onChange={(event) => changeAlertSound(event.target.value)}
                      className="h-9 rounded-md border border-[#e3dfd3] bg-[#fdfcf8] px-2 text-[12px] text-[#2c2920] focus:outline-none focus:ring-2 focus:ring-[#e7c9b7]"
                    >
                      {SOUND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {t(option.labelKey)}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={testAlerts}
                      className="grid h-9 w-9 place-items-center rounded-md border border-[#e3dfd3] bg-[#fdfcf8] text-[#56503f] transition hover:bg-[#f8f6ef] hover:text-[#14110b]"
                      aria-label={t("notif.testAlerts")}
                      title={t("notif.testAlerts")}
                    >
                      <Play className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <label className="grid grid-cols-[48px_1fr_36px] items-center gap-2 text-[10.5px] text-[#8a8472]">
                    <span>{t("notif.volume")}</span>
                    <input
                      type="range"
                      min={20}
                      max={100}
                      step={5}
                      value={Math.round(alertVolume * 100)}
                      onChange={(event) => changeAlertVolume(Number(event.target.value) / 100)}
                      onMouseUp={() => void playNotificationSound()}
                      onTouchEnd={() => void playNotificationSound()}
                      aria-label={t("notif.volume")}
                    />
                    <span className="text-right font-mono">{Math.round(alertVolume * 100)}%</span>
                  </label>
                </div>
              )}
            </div>

            <div className="min-h-24 flex-1 overflow-y-auto">
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
                    background: n.is_read ? "transparent" : "var(--erp-accent-soft)",
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
                          background: "var(--erp-accent)",
                        }}
                      />
                    )}
                    {n.is_read && <span className="w-1.5 shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <div
                        className={`break-words text-[13px] font-medium ${
                          n.is_read ? "text-[#56503f]" : "text-[#14110b]"
                        }`}
                      >
                        {n.title}
                      </div>
                      {n.message && (
                        <div className="mt-0.5 break-words text-[11.5px] text-[#56503f]">
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
      ), document.body)}
    </div>
  );
}
