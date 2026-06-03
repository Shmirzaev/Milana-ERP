"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { Lang, LANG_NAMES, useT } from "@/lib/i18n";
import BrandLogo from "@/components/BrandLogo";

const LANGS: Lang[] = ["en", "ru", "uz"];
const SHORT: Record<Lang, string> = { en: "EN", ru: "RU", uz: "UZ" };

type LoginPanel = {
  active_orders: number;
  todays_receipts: number;
  late_orders: number;
  production_14d: number[];
  open_tasks: Array<{ title: string; priority: string; status: string }>;
};

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

function priorityColor(priority?: string) {
  if (priority === "urgent") return "#c2410c";
  if (priority === "high") return "#1e5fb3";
  if (priority === "medium") return "#1f7a4d";
  return "#8a8472";
}

export default function LoginPage() {
  const { t, lang, setLang } = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotMsg, setForgotMsg] = useState("");
  const [forgotError, setForgotError] = useState("");
  const [forgotLoading, setForgotLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [clientTz, setClientTz] = useState("UTC");
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) setClientTz(tz);
    } catch {
      setClientTz("UTC");
    }
  }, []);

  useEffect(() => {
    setNow(new Date());
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const { data: panel } = useSWR<LoginPanel>(`/api/auth/login-panel?tz=${encodeURIComponent(clientTz)}`, fetcher);

  const locale = lang === "ru" ? "ru-RU" : lang === "uz" ? "uz-UZ" : "en-US";
  const moneyFmt = useMemo(() => new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }), [locale]);
  const intFmt = useMemo(() => new Intl.NumberFormat(locale), [locale]);

  const series = panel?.production_14d?.length ? panel.production_14d : Array.from({ length: 14 }, () => 0);
  const chart = useMemo(() => {
    const width = 312;
    const bottom = 70;
    const top = 14;
    const step = series.length > 1 ? width / (series.length - 1) : width;
    const max = Math.max(1, ...series);
    const min = Math.min(...series);
    const range = Math.max(1, max - min);
    const pts = series.map((v, i) => {
      const x = i * step;
      const y = bottom - ((v - min) / range) * (bottom - top);
      return [x, clamp(y, top, bottom)] as const;
    });
    const linePath = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    const areaPath = `${linePath} L${width} 90 L0 90 Z`;
    return { linePath, areaPath, step };
  }, [series]);

  const openTasks = panel?.open_tasks || [];

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.login(email, password);
      window.location.href = "/";
    } catch (err: any) {
      setError(err.message || t("auth.loginFailed"));
    } finally {
      setLoading(false);
    }
  }

  function openForgotPassword() {
    setForgotEmail(email);
    setForgotMsg("");
    setForgotError("");
    setForgotOpen(true);
  }

  async function submitForgotPassword(e: React.FormEvent) {
    e.preventDefault();
    setForgotMsg("");
    setForgotError("");
    setForgotLoading(true);
    try {
      await api.forgotPassword(forgotEmail);
      setForgotMsg(t("login.forgotSuccess"));
    } catch (err: any) {
      const message = String(err?.message || "");
      setForgotError(
        message.startsWith("404:") || message.startsWith("501:")
          ? t("login.forgotUnavailable")
          : message.toLowerCase().includes("backend is not responding")
          ? t("login.forgotRetry")
          : message || t("login.forgotError")
      );
    } finally {
      setForgotLoading(false);
    }
  }

  const dateStr = now
    ? new Intl.DateTimeFormat(
        locale,
        { day: "numeric", month: "long", year: "numeric", weekday: "long" }
      ).format(now)
    : "";
  const timeStr = now
    ? new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(now)
    : "";

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-[1.1fr_1fr] bg-[#f7f6f1] text-[#14110b]">
      <aside className="relative hidden lg:flex flex-col p-10 bg-[#f1efe8] border-r border-[#e3dfd3] overflow-hidden">
        <svg className="absolute inset-0 w-full h-full opacity-60 pointer-events-none" aria-hidden>
          <defs>
            <pattern id="loginGrid" width="24" height="24" patternUnits="userSpaceOnUse">
              <path d="M24 0H0V24" fill="none" stroke="#dcd6c2" strokeWidth="0.5" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#loginGrid)" />
        </svg>

        <header className="relative flex items-center justify-between mb-9">
          <div className="flex items-center">
            <BrandLogo alt={t("app.name")} className="h-14 w-auto max-w-[240px]" />
          </div>
	          <div className="text-[11px] tracking-wider text-[#8a8472] text-right leading-tight">
	            <div>{dateStr}</div>
	            <div>{timeStr} · {clientTz}</div>
	          </div>
        </header>

        <div className="relative mb-7 max-w-[540px]">
          <div className="text-[11px] tracking-[0.22em] uppercase text-[#c2410c] mb-3.5 flex items-center gap-2.5">
            <span className="inline-block w-7 h-px bg-[#c2410c]" />
            {t("login.kicker")}
          </div>
          <h1
            className="m-0 text-[48px] leading-[1.05] tracking-[-0.01em]"
            style={{ fontFamily: "'Instrument Serif', 'Iowan Old Style', Palatino, serif", fontWeight: 400 }}
          >
            {t("login.heroPrefix")}{" "}
            <em className="text-[#c2410c] not-italic" style={{ fontStyle: "italic" }}>{t("login.heroAccent")}</em>{" "}
            {t("login.heroSuffix")}
          </h1>
        </div>

        <div className="relative grid grid-cols-3 gap-3.5">
          <KpiPeek kicker={t("login.kpiOrders")} value={intFmt.format(panel?.active_orders || 0)} color="#1f7a4d" />
          <KpiPeek kicker={t("login.kpiReceipts")} value={moneyFmt.format(panel?.todays_receipts || 0)} color="#c2410c" />
          <KpiPeek kicker={t("login.kpiBackorders")} value={intFmt.format(panel?.late_orders || 0)} color="#1e5fb3" />
        </div>

        <div className="relative mt-3.5 grid grid-cols-[1.4fr_1fr] gap-3.5">
          <div className="rounded-[10px] border border-[#e3dfd3] bg-[#fdfcf8] p-4">
            <div className="flex justify-between items-baseline mb-2.5">
              <div className="text-[12px] font-semibold text-[#14110b]">{t("login.production")}</div>
              <div className="text-[10.5px] tracking-wider text-[#8a8472]">{t("login.units")}</div>
            </div>
            <svg viewBox="0 0 320 90" className="w-full h-[90px]" aria-hidden>
              <defs>
                <linearGradient id="loginLine" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#c2410c" stopOpacity="0.18" />
                  <stop offset="100%" stopColor="#c2410c" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path
                d={chart.areaPath}
                fill="url(#loginLine)"
              />
              <path
                d={chart.linePath}
                fill="none"
                stroke="#c2410c"
                strokeWidth="1.6"
              />
              {series.map((_, i) => (
                <line
                  key={i}
                  x1={i * chart.step}
                  y1="78"
                  x2={i * chart.step}
                  y2="82"
                  stroke="#e3dfd3"
                  strokeWidth="1"
                />
              ))}
            </svg>
          </div>
          <div className="rounded-[10px] border border-[#e3dfd3] bg-[#fdfcf8] p-4">
            <div className="text-[12px] font-semibold mb-2.5">{t("login.openTasks")}</div>
            <div className="flex flex-col gap-1.5">
              {openTasks.length ? openTasks.map((row, idx) => (
                <div key={`${row.title}-${idx}`} className="flex items-center gap-2 text-[11.5px] text-[#2c2920]">
                  <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: priorityColor(row.priority) }} />
                  {row.title}
                </div>
              )) : (
                <div className="text-[11.5px] text-[#8a8472]">{t("tasks.empty")}</div>
              )}
            </div>
          </div>
        </div>

        <div
          className="absolute inset-0 pointer-events-none"
          style={{ background: "linear-gradient(180deg, transparent 0%, transparent 50%, rgba(241,239,232,0.7) 100%)" }}
        />
      </aside>

      <section className="relative flex items-center justify-center px-6 py-12 lg:p-14 bg-[#fdfcf8]">
        <div className="absolute top-6 right-6 flex items-center gap-1">
          {LANGS.map((l, i) => (
            <span key={l} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setLang(l)}
                aria-label={LANG_NAMES[l]}
                className={`px-1.5 py-1 text-[11.5px] uppercase tracking-[0.08em] rounded transition ${
                  lang === l ? "text-[#14110b] font-semibold" : "text-[#8a8472] hover:text-[#14110b]"
                }`}
              >
                {SHORT[l]}
              </button>
              {i < LANGS.length - 1 && <span className="text-[#ded9ca]">·</span>}
            </span>
          ))}
        </div>

        <div className="w-full max-w-[380px]">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 mb-5 rounded-full bg-[#fbe9dd] text-[#9a3308] text-[11px] font-semibold tracking-wider">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#c2410c]" />
            {t("login.presence")}
          </div>
          <h2
            className="m-0 mb-2.5 text-[42px] leading-[1.04] tracking-[-0.01em]"
            style={{ fontFamily: "'Instrument Serif', 'Iowan Old Style', Palatino, serif", fontWeight: 400 }}
          >
            {t("login.signInTitle")}
          </h2>
          <p className="m-0 mb-8 text-sm text-[#56503f]">{t("login.subtitle")}</p>

          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <Field
              label={t("auth.email")}
              type="email"
              value={email}
              onChange={setEmail}
              iconPath="M2 6l8 5 8-5M2 6h16v10H2z"
              autoComplete="email"
            />
            <Field
              label={t("auth.password")}
              type="password"
              value={password}
              onChange={setPassword}
              iconPath="M5 9V7a3 3 0 016 0v2M3 9h10v8H3z"
              trailing={t("login.forgot")}
              onTrailingClick={openForgotPassword}
              autoComplete="current-password"
            />

            {error && (
              <div className="flex items-start gap-2 text-[12.5px] text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="mt-0.5 shrink-0" aria-hidden>
                  <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.2" />
                  <path d="M8 5v4M8 11h.01" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                </svg>
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary w-full justify-center mt-1.5"
              style={{ height: 44, fontSize: 13.5 }}
            >
              {loading ? t("auth.signingIn") : t("login.continue")}
              {!loading && (
                <svg width="14" height="14" viewBox="0 0 20 20" fill="none" aria-hidden>
                  <path d="M4 10h12m0 0l-4-4m4 4l-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </form>

          <div className="mt-8 text-[11px] tracking-wider text-[#8a8472]">© 2026 Milana Ecosystem · v4.2.1</div>
        </div>
      </section>

      {forgotOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#14110b]/35 px-4">
          <div className="w-full max-w-[380px] rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] p-5 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="m-0 text-lg font-semibold text-[#14110b]">{t("login.forgotTitle")}</h3>
                <p className="m-0 mt-1 text-sm text-[#56503f]">{t("login.forgotHelp")}</p>
              </div>
              <button
                type="button"
                onClick={() => setForgotOpen(false)}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-[#8a8472] hover:bg-[#f1efe8] hover:text-[#14110b]"
                aria-label={t("common.cancel")}
              >
                <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden>
                  <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            <form onSubmit={submitForgotPassword} className="mt-5 space-y-3">
              <div>
                <label className="label">{t("auth.email")}</label>
                <input
                  className="input"
                  type="email"
                  data-testid="forgot-password-email"
                  value={forgotEmail}
                  onChange={(e) => setForgotEmail(e.target.value)}
                  autoComplete="email"
                  required
                  style={{ height: 42, fontSize: 14 }}
                />
              </div>

              {forgotMsg && (
                <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-[12.5px] text-green-700">
                  {forgotMsg}
                </div>
              )}
              {forgotError && (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-700">
                  {forgotError}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => setForgotOpen(false)} className="btn">
                  {t("common.cancel")}
                </button>
                <button type="submit" disabled={forgotLoading} data-testid="forgot-password-submit" className="btn btn-primary">
                  {forgotLoading ? t("login.forgotSending") : t("login.forgotSend")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  type,
  value,
  onChange,
  iconPath,
  trailing,
  onTrailingClick,
  autoComplete,
}: {
  label: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
  iconPath: string;
  trailing?: string;
  onTrailingClick?: () => void;
  autoComplete?: string;
}) {
  return (
    <div>
      <div className="flex justify-between items-baseline">
        <label className="label">{label}</label>
        {trailing && (
          <button
            type="button"
            onClick={onTrailingClick}
            data-testid="forgot-password-open"
            className="-mr-1 rounded px-1 py-0.5 text-[11.5px] font-medium text-[#c2410c] no-underline hover:bg-[#fbe9dd] hover:underline"
          >
            {trailing}
          </button>
        )}
      </div>
      <div className="relative">
        <svg
          width="14"
          height="14"
          viewBox="0 0 20 20"
          fill="none"
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a8472] pointer-events-none"
          aria-hidden
        >
          <path d={iconPath} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <input
          className="input"
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          required
          style={{ height: 42, paddingLeft: 36, fontSize: 14 }}
        />
      </div>
    </div>
  );
}

function KpiPeek({ kicker, value, delta, color }: { kicker: string; value: string; delta?: string; color: string }) {
  return (
    <div className="relative overflow-hidden rounded-[10px] border border-[#e3dfd3] bg-[#fdfcf8] p-4">
      <div className="text-[10.5px] tracking-[0.14em] uppercase text-[#8a8472] font-semibold">{kicker}</div>
      <div className="flex items-baseline gap-2 mt-1.5">
        <div
          className="text-[30px] leading-none tracking-[-0.01em]"
          style={{ fontFamily: "'Instrument Serif', 'Iowan Old Style', Palatino, serif", fontWeight: 400 }}
        >
          {value}
        </div>
        {delta ? (
          <div className="text-[11.5px] font-semibold" style={{ color }}>
            {delta}
          </div>
        ) : null}
      </div>
      <div className="absolute left-0 bottom-0 h-[2px] w-full opacity-85" style={{ background: color }} />
    </div>
  );
}
