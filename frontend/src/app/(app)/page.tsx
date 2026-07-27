"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { CalendarDays, Download, Factory, Plus, TrendingDown, TrendingUp } from "lucide-react";
import { fetcher } from "@/lib/api";
import { DASHBOARD_SWR_OPTIONS } from "@/lib/liveData";
import PageHeader from "@/components/PageHeader";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";

type FilterKind = "all" | "client_order" | "branded_stock_sale";
type DatePreset = "all" | "today" | "yesterday" | "tomorrow" | "this_week" | "this_month" | "current_year" | "custom";

type ActiveProductionOrder = {
  id: number;
  order_no: string;
  customer: string;
  qty: number;
  progress: number;
  status: string;
  deadline: string | null;
  deadline_label?: string;
  value: number;
  type: string;
  order_type?: string;
};

function startOfDay(d: Date): Date {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}

function endOfDay(d: Date): Date {
  const r = new Date(d);
  r.setHours(23, 59, 59, 999);
  return r;
}

function firstDayOfWeek(d: Date): Date {
  const r = startOfDay(d);
  const day = (r.getDay() + 6) % 7;
  r.setDate(r.getDate() - day);
  return r;
}

function firstDayOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1, 0, 0, 0, 0);
}

function lastDayOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59, 999);
}

function firstDayOfYear(d: Date): Date {
  return new Date(d.getFullYear(), 0, 1, 0, 0, 0, 0);
}

function lastDayOfYear(d: Date): Date {
  return new Date(d.getFullYear(), 11, 31, 23, 59, 59, 999);
}

function formatRangeLabel(preset: DatePreset): string {
  if (preset === "today") return "home.range.today";
  if (preset === "yesterday") return "home.range.yesterday";
  if (preset === "tomorrow") return "home.range.tomorrow";
  if (preset === "this_week") return "home.range.thisWeek";
  if (preset === "this_month") return "home.range.thisMonth";
  if (preset === "current_year") return "home.range.currentYear";
  if (preset === "custom") return "home.range.custom";
  return "home.range.all";
}

function Kpi({ label, value, sub, tone = "neutral", visual }: { label: string; value: any; sub?: string; tone?: "neutral" | "bad" | "good"; visual?: React.ReactNode }) {
  return (
    <div className={`card p-5 ${tone === "bad" ? "border-[#d97706] bg-[#fff7df]" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="label">{label}</div>
          <div className="mt-1 text-3xl font-semibold tracking-tight text-[#14110b]">{value ?? "-"}</div>
          {sub ? (
            <div className={`mt-2 flex items-center gap-1 text-xs ${tone === "bad" ? "text-red-600" : tone === "good" ? "text-green-700" : "text-[#8a8472]"}`}>
              {tone === "bad" ? <TrendingDown className="h-3.5 w-3.5" /> : tone === "good" ? <TrendingUp className="h-3.5 w-3.5" /> : null}
              {sub}
            </div>
          ) : null}
        </div>
        {visual}
      </div>
    </div>
  );
}

function Money({ value }: { value: number }) {
  return <span className="mono">${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>;
}

function toCsvCell(v: unknown): string {
  const s = String(v ?? "");
  if (s.includes(",") || s.includes("\"") || s.includes("\n")) return `"${s.replace(/"/g, "\"\"")}"`;
  return s;
}

export default function HomePage() {
  const { me } = useMe();
  const { t } = useT();
  const [clientTz, setClientTz] = useState("UTC");
  useEffect(() => {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) setClientTz(tz);
    } catch {
      setClientTz("UTC");
    }
  }, []);

  const { data: mgmt } = useSWR<any>(
    can(me, "management.view", "*") ? `/api/dashboard/management?tz=${encodeURIComponent(clientTz)}` : null,
    fetcher,
    DASHBOARD_SWR_OPTIONS,
  );
  const { data: fin } = useSWR<any>(
    can(me, "finance.view", "*") ? "/api/dashboard/finance" : null,
    fetcher,
    DASHBOARD_SWR_OPTIONS,
  );
  const {
    data: activeProductionData,
    error: activeProductionError,
    isLoading: activeProductionLoading,
  } = useSWR<ActiveProductionOrder[]>(
    "/api/dashboard/active-production",
    fetcher,
    DASHBOARD_SWR_OPTIONS,
  );
  const activeProduction = useMemo(() => activeProductionData ?? [], [activeProductionData]);
  const showActiveProductionError = Boolean(activeProductionError && !activeProductionData);

  const [kind, setKind] = useState<FilterKind>("all");
  const [datePreset, setDatePreset] = useState<DatePreset>("this_week");
  const [showDateMenu, setShowDateMenu] = useState(false);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const dateRange = useMemo(() => {
    const now = new Date();
    if (datePreset === "all") return { start: null as Date | null, end: null as Date | null };
    if (datePreset === "today") return { start: startOfDay(now), end: endOfDay(now) };
    if (datePreset === "yesterday") {
      const d = new Date(now);
      d.setDate(d.getDate() - 1);
      return { start: startOfDay(d), end: endOfDay(d) };
    }
    if (datePreset === "tomorrow") {
      const d = new Date(now);
      d.setDate(d.getDate() + 1);
      return { start: startOfDay(d), end: endOfDay(d) };
    }
    if (datePreset === "this_week") {
      const start = firstDayOfWeek(now);
      const end = new Date(start);
      end.setDate(start.getDate() + 6);
      return { start, end: endOfDay(end) };
    }
    if (datePreset === "this_month") return { start: firstDayOfMonth(now), end: lastDayOfMonth(now) };
    if (datePreset === "current_year") return { start: firstDayOfYear(now), end: lastDayOfYear(now) };
    if (datePreset === "custom") {
      if (!customFrom && !customTo) return { start: null as Date | null, end: null as Date | null };
      const start = customFrom ? startOfDay(new Date(customFrom)) : null;
      const end = customTo ? endOfDay(new Date(customTo)) : null;
      return { start, end };
    }
    return { start: null as Date | null, end: null as Date | null };
  }, [datePreset, customFrom, customTo]);

  const prodUrl = useMemo(() => {
    const params = new URLSearchParams();
    if (dateRange.start) params.set("start", dateRange.start.toISOString());
    if (dateRange.end) params.set("end", dateRange.end.toISOString());
    const qs = params.toString();
    return qs ? `/api/dashboard/production?${qs}` : "/api/dashboard/production";
  }, [dateRange.start, dateRange.end]);
  const { data: prod } = useSWR<any>(prodUrl, fetcher, DASHBOARD_SWR_OPTIONS);

  const activeOrders = useMemo(() => {
    return activeProduction
      .filter((o) => kind === "all" || String(o.type || o.order_type || "") === kind)
      .slice(0, 6);
  }, [activeProduction, kind]);

  const activeOrdersTotal = activeProduction.length;

  function exportOrders() {
    if (!activeOrders.length) return;
    const rows = activeOrders.map((o) => [
      o.order_no,
      o.customer,
      o.type || o.order_type || "",
      o.status,
      o.deadline || "",
      Number(o.value || 0).toFixed(2),
    ]);
    const header = ["order_no", "customer", "order_type", "status", "deadline", "total_amount"];
    const csv = [header, ...rows].map((r) => r.map(toCsvCell).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `home-orders-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function applyCustomRange() {
    setDatePreset("custom");
    setShowDateMenu(false);
  }

  const stageRows = [
    { name: t("dash.cutting"), value: Number(prod?.cutting_output || 0) },
    { name: t("dash.printing"), value: Number(prod?.printing_output || 0) },
    { name: t("dash.sewing"), value: Number(prod?.sewing_output || 0) },
    { name: t("dash.packaging"), value: Number(prod?.packaging_output || 0) },
  ];
  const maxStageValue = Math.max(1, ...stageRows.map((r) => r.value));

  return (
    <div>
      <PageHeader
        eyebrow={t("nav.dashboard")}
        title={t("home.greeting", { name: me?.name?.split(" ")[0] || "Aziza" })}
        subtitle={t("home.subtitle", { range: t(formatRangeLabel(datePreset)) })}
        actions={(
          <>
            <div className="relative">
              <button className="btn" onClick={() => setShowDateMenu((v) => !v)}>
                <CalendarDays />{t(formatRangeLabel(datePreset))}
              </button>
              {showDateMenu ? (
                <div className="absolute right-0 top-10 z-20 w-64 rounded-lg border border-[#ded9ca] bg-[#fdfcf8] p-3 shadow-lg">
                  <div>
                    <div className="label">{t("home.datePreset")}</div>
                    <select
                      className="input"
                      value={datePreset}
                      onChange={(e) => {
                        const next = e.target.value as DatePreset;
                        setDatePreset(next);
                        if (next !== "custom") setShowDateMenu(false);
                      }}
                    >
                      <option value="today">{t("home.range.today")}</option>
                      <option value="yesterday">{t("home.range.yesterday")}</option>
                      <option value="tomorrow">{t("home.range.tomorrow")}</option>
                      <option value="this_week">{t("home.range.thisWeek")}</option>
                      <option value="this_month">{t("home.range.thisMonth")}</option>
                      <option value="current_year">{t("home.range.currentYear")}</option>
                      <option value="all">{t("home.range.all")}</option>
                      <option value="custom">{t("home.range.custom")}</option>
                    </select>
                  </div>
                  <div className="mt-3 border-t border-[#ecebe3] pt-3">
                    <div className="label">{t("home.customDates")}</div>
                    <div className="grid grid-cols-1 gap-2">
                      <input
                        type="date"
                        className="input"
                        value={customFrom}
                        onChange={(e) => setCustomFrom(e.target.value)}
                      />
                      <input
                        type="date"
                        className="input"
                        value={customTo}
                        onChange={(e) => setCustomTo(e.target.value)}
                      />
                      <button className="btn btn-primary" onClick={applyCustomRange}>{t("home.applyCustomRange")}</button>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
            <button className="btn" onClick={exportOrders} disabled={!activeOrders.length}>
              <Download />{t("sales.export")}
            </button>
            <a href="/sales-orders/new" className="btn btn-primary"><Plus />{t("btn.newOrder").replace("+ ", "")}</a>
          </>
        )}
      />

      <div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Kpi label={t("dash.activeOrders")} value={activeOrdersTotal || mgmt?.active_orders || 0} sub="Planning + confirmed + in production" tone="good" />
        <Kpi label={t("dash.production")} value={(Number(prod?.cutting_output || 0) + Number(prod?.printing_output || 0) + Number(prod?.sewing_output || 0) + Number(prod?.packaging_output || 0)).toLocaleString()} tone="good" />
        <Kpi label={t("dash.lateOrders")} value={mgmt?.late_orders ?? 0} tone={Number(mgmt?.late_orders || 0) > 0 ? "bad" : "good"} />
        <Kpi label={t("dash.todaysDefects")} value={Number(mgmt?.todays_defects || 0).toLocaleString()} tone={Number(mgmt?.todays_defects || 0) > 0 ? "bad" : "good"} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.55fr_1fr]">
        <div className="card">
          <div className="flex flex-col items-start gap-3 border-b border-[#ecebe3] px-4 py-3 sm:flex-row sm:items-center">
            <div className="min-w-0">
              <h2 className="app-card-title">{t("home.activeProduction")}</h2>
              <span className="text-xs text-[#8a8472]">{t("home.ordersInFlight", { count: activeOrders.length, value: activeOrders.length })}</span>
            </div>
            <div className="flex w-full flex-col items-stretch gap-2 sm:ml-auto sm:w-auto sm:flex-row sm:items-center sm:overflow-x-auto">
              <div className="shrink-0 rounded-md border border-[#ded9ca] bg-[#f1efe8] p-0.5 text-xs">
                <button className={`px-3 py-1 ${kind === "all" ? "rounded bg-[#fdfcf8] shadow-sm" : "text-[#56503f]"}`} onClick={() => setKind("all")}>{t("sales.tab.all")}</button>
                <button className={`px-3 py-1 ${kind === "client_order" ? "rounded bg-[#fdfcf8] shadow-sm" : "text-[#56503f]"}`} onClick={() => setKind("client_order")}>{t("orderType.client")}</button>
                <button className={`px-3 py-1 ${kind === "branded_stock_sale" ? "rounded bg-[#fdfcf8] shadow-sm" : "text-[#56503f]"}`} onClick={() => setKind("branded_stock_sale")}>{t("orderType.branded")}</button>
              </div>
              <a href="/sales-orders" className="btn btn-ghost shrink-0">{t("home.viewAll")} -&gt;</a>
            </div>
          </div>
          <div className="divide-y divide-[#ecebe3] md:hidden">
            {activeProductionLoading ? (
              <div className="p-4 text-sm text-[#8a8472]">{t("common.loading")}</div>
            ) : showActiveProductionError ? (
              <div className="p-4 text-sm text-red-600">{t("page.home.activeProductionError")}</div>
            ) : !activeOrders.length ? (
              <div className="p-4 text-sm text-[#8a8472]">{t("page.home.noOrdersSelectedFilter")}</div>
            ) : activeOrders.map((o) => {
              const pct = Math.max(0, Math.min(100, Number(o.progress || 0)));
              return (
                <article key={o.id} className="p-4">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <a href={`/sales-orders/${o.id}`} className="mono block truncate font-semibold text-[#14110b]">{o.order_no}</a>
                      <div className="mt-1 truncate text-sm font-medium text-[#14110b]">{o.customer || t("sales.unknownCustomer")}</div>
                    </div>
                    <span className="badge shrink-0 bg-[#fbe9dd] text-[#c2410c]">{statusLabel(o.status, t)}</span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <div className="label">{t("field.qty")}</div>
                      <div className="mono font-semibold">{Number(o.qty || 0).toLocaleString()}</div>
                    </div>
                    <div>
                      <div className="label">{t("field.value")}</div>
                      <div className="font-semibold"><Money value={Number(o.value || 0)} /></div>
                    </div>
                    <div>
                      <div className="label">{t("field.deadline")}</div>
                      <div className="mono text-[#56503f]">
                        {o.deadline_label || (o.deadline ? new Date(o.deadline).toLocaleDateString("en-US", { month: "short", day: "2-digit" }) : "-")}
                      </div>
                    </div>
                    <div>
                      <div className="label">{t("page.processes.progress")}</div>
                      <div className="flex items-center gap-2">
                        <div className="mini-bar flex-1"><span style={{ width: `${pct}%` }} /></div>
                        <span className="mono text-xs text-[#8a8472]">{pct}%</span>
                      </div>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.orderNo")}</th><th>{t("field.customer")}</th><th>{t("field.qty")}</th><th>{t("page.processes.progress")}</th><th>{t("common.status")}</th><th>{t("field.deadline")}</th><th className="text-right">{t("field.value")}</th>
                </tr>
              </thead>
              <tbody>
                {activeProductionLoading ? (
                  <tr><td colSpan={7} className="px-4 py-6 text-sm text-[#8a8472]">{t("common.loading")}</td></tr>
                ) : showActiveProductionError ? (
                  <tr><td colSpan={7} className="px-4 py-6 text-sm text-red-600">{t("page.home.activeProductionError")}</td></tr>
                ) : !activeOrders.length ? (
                  <tr><td colSpan={7} className="px-4 py-6 text-sm text-[#8a8472]">{t("page.home.noOrdersSelectedFilter")}</td></tr>
                ) : activeOrders.map((o) => {
                  const pct = Math.max(0, Math.min(100, Number(o.progress || 0)));
                  return (
                    <tr key={o.id}>
                      <td><a href={`/sales-orders/${o.id}`} className="mono font-medium">{o.order_no}</a></td>
                      <td>{o.customer || t("sales.unknownCustomer")}</td>
                      <td className="mono">{Number(o.qty || 0).toLocaleString()}</td>
                      <td className="min-w-36">
                        <div className="flex items-center gap-2">
                          <div className="mini-bar flex-1"><span style={{ width: `${pct}%` }} /></div>
                          <span className="mono text-xs text-[#8a8472]">{pct}%</span>
                        </div>
                      </td>
                      <td><span className="badge bg-[#fbe9dd] text-[#c2410c]">{statusLabel(o.status, t)}</span></td>
                      <td className="mono text-[#8a8472]">{o.deadline_label || (o.deadline ? new Date(o.deadline).toLocaleDateString("en-US", { month: "short", day: "2-digit" }) : "-")}</td>
                      <td className="text-right"><Money value={Number(o.value || 0)} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="border-b border-[#ecebe3] px-4 py-3">
            <h2 className="app-card-title">{t("home.stationsToday")}</h2>
            <div className="text-xs text-[#8a8472]">{t("home.piecesProcessed")}</div>
          </div>
          <div className="space-y-5 p-4">
            {stageRows.map(({ name, value }, i) => (
              <div key={name}>
                <div className="mb-2 flex items-center justify-between text-sm">
                  <div className="font-medium">{name} {i === 2 && <span className="badge bg-[#fbe9dd] text-[#c2410c]">{t("home.live")}</span>}</div>
                  <div className="mono"><b>{value.toLocaleString()}</b></div>
                </div>
                <div className="mini-bar">
                  <span className={i === 2 ? "bg-[#c2410c]" : ""} style={{ width: `${Math.min(100, (value / maxStageValue) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {fin && (
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="card p-4">
            <h3 className="app-card-title">{t("dash.finance")}</h3>
            <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <div><div className="label">{t("dash.revenue")}</div><div className="text-xl"><Money value={fin.revenue_total || 0} /></div></div>
              <div><div className="label">{t("dash.payments")}</div><div className="text-xl"><Money value={fin.payments_received || 0} /></div></div>
            </div>
          </div>
          <a href="/processes" className="card p-4 transition hover:border-[#c2410c]">
            <Factory className="mb-3 h-5 w-5 text-[#c2410c]" />
            <h3 className="app-card-title">{t("page.processes.title")}</h3>
            <p className="mt-1 text-sm text-[#8a8472]">{t("home.liveProcessTrackerDesc")}</p>
          </a>
          {can(me, "sewing.workspace") && (
            <a href="/sewing/flows" className="card p-4 transition hover:border-[#c2410c]">
              <Factory className="mb-3 h-5 w-5 text-[#1f7a4d]" />
              <h3 className="app-card-title">{t("nav.sewingFloor")}</h3>
              <p className="mt-1 text-sm text-[#8a8472]">{t("home.sewingFloorDesc")}</p>
            </a>
          )}
        </div>
      )}
    </div>
  );
}
