"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { ArrowRight, Download, Plus, RefreshCw, Search } from "lucide-react";
import { fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { ledgerNote, messages, statusNames } from "./messages";
import { businessDate, Overview, periodDates, stageColors, stageKeys } from "./types";
import { DepartmentBars, OrderDonut, OutputLineChart } from "./DashboardCharts";

const surface = { background: "var(--erp-surface)", borderColor: "var(--erp-border)", color: "var(--erp-text)" };
const muted = { color: "var(--erp-text-soft)" };
function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return <section className="min-w-0 rounded-lg border" style={surface}><div className="px-5 pt-5"><h2 className="text-base font-semibold">{title}</h2><p className="mt-1 text-xs" style={muted}>{subtitle}</p></div>{children}</section>;
}

export default function ManagementDashboard() {
  const { me } = useMe();
  const { t, lang } = useT();
  const copy = messages[lang];
  const stageLabel = (status: string) => statusNames[lang][status] || status;
  const [days, setDays] = useState(30);
  const [today, setToday] = useState(() => businessDate());
  const [kind, setKind] = useState("all");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = setInterval(() => setToday(businessDate()), 60_000);
    return () => clearInterval(timer);
  }, []);
  const range = periodDates(days, today);
  const { data, error, isLoading, isValidating, mutate } = useSWR<Overview>(
    can(me, "management.view") ? `/api/dashboard/overview?start=${range.start}&end=${range.end}` : null,
    fetcher, { refreshInterval: 30_000, refreshWhenHidden: false, keepPreviousData: false },
  );
  const { data: finance, error: financeError } = useSWR<{ revenue_total: number; payments_received: number }>(can(me, "finance.view") ? "/api/dashboard/finance" : null, fetcher);
  const labels = stageKeys.map(k => t(`dash.${k}`));
  const statusOrder = ["new", "planning", "waiting_material", "cutting", "printing", "sewing", "packaging", "storage_transfer"];
  const colors = ["#999182", "#a88130", "#8f7766", stageColors[0], stageColors[1], stageColors[2], stageColors[3], "#566c77"];
  const rows = statusOrder.filter(k => data?.by_status[k]).map(k => ({ label: stageLabel(k), value: data!.by_status[k], color: colors[statusOrder.indexOf(k)] }));
  const orders = data?.orders.filter(o => (kind === "all" || o.type === kind) && o.order_no.toLocaleLowerCase().includes(search.toLocaleLowerCase())) ?? [];
  const typeLabel = (type: string) => type === "client_order" ? copy.client : type === "branded_stock" ? copy.branded : type === "service_order" ? copy.service : type;
  const n = (v: number | undefined) => v === undefined ? "—" : v.toLocaleString();
  function exportOutput() {
    if (!data) return;
    const csv = [["date", ...stageKeys], ...data.daily.map(p => [p.date, ...stageKeys.map(k => p[k])])].map(row => row.join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `production-output-${data.start}-${data.end}.csv`; link.click(); URL.revokeObjectURL(url);
  }
  const canOpenOrders = can(me, "planning.view", "planning.production", "processes.view");
  const orderHref = (o: Overview["orders"][number]) => o.source_type === "usluga"
    ? can(me, "usluga.view", "usluga.manage", "usluga.handover") ? `/usluga/orders/${o.id}` : null
    : canOpenOrders ? `/production-orders/${o.id}` : null;
  return <div className="mx-auto max-w-[1600px] pb-4" style={{ color: "var(--erp-text)" }}>
    <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold tracking-tight">{copy.title}</h1><p className="mt-1.5 text-sm" style={muted}>{copy.subtitle}</p></div>
      <div className="flex flex-wrap gap-2">
        <button className="btn" disabled={!data} onClick={exportOutput}><Download size={16} />{copy.export}</button>
        <button className="btn" aria-label={copy.refresh} title={copy.refresh} disabled={isValidating} onClick={() => { setToday(businessDate()); void mutate(); }}><RefreshCw size={16} /></button>
        {can(me, "sales.orders") && <a href="/sales-orders/new" className="btn btn-primary"><Plus size={16} />{copy.newOrder}</a>}
      </div>
    </header>
    {error && <div role="alert" className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "var(--erp-danger)", color: "var(--erp-danger)" }}>{data ? copy.stale : copy.error} <button className="ml-3 underline" onClick={() => void mutate()}>{copy.refresh}</button></div>}
    <div className="mb-5 grid grid-cols-2 divide-x rounded-lg border lg:grid-cols-4" style={surface}>
      {[
        [copy.active, data?.active_orders, copy.current], [copy.planned, data?.planned_quantity, copy.current],
        [copy.late, data?.late_orders, copy.current], [copy.packed, data?.totals.packaging, copy.period],
      ].map(([label, value, sub], i) => <div key={String(label)} className="px-5 py-5" style={{ borderColor: "var(--erp-border-soft)" }}><div className="text-sm" style={muted}>{label}</div><div className="mt-2 text-3xl font-semibold tabular-nums tracking-tight" style={i === 2 && Number(value) > 0 ? { color: "var(--erp-danger)" } : undefined}>{n(value as number | undefined)}</div><div className="mt-2 text-xs" style={muted}>{sub}</div></div>)}
    </div>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3"><label htmlFor="dashboard-period" className="text-sm font-semibold">{copy.period}</label><select id="dashboard-period" className="input !w-auto" value={days} onChange={e => setDays(Number(e.target.value))}><option value={7}>{copy.days7}</option><option value={30}>{copy.days30}</option><option value={90}>{copy.days90}</option></select></div>
      <span className="text-xs tabular-nums" style={muted}>{range.start} — {range.end} · Asia/Tashkent</span>
    </div>
    {isLoading && <div role="status" className="mb-4 rounded-lg border p-10 text-center" style={surface}>{copy.loading}</div>}
    {data && <>
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <Panel title={copy.trend} subtitle={copy.records}>
          <OutputLineChart points={data.daily} labels={labels} title={copy.trend} />
          <p className="px-5 pb-3 text-xs leading-5" style={muted}>{ledgerNote[lang]}</p>
          {!Object.values(data.totals).some(Boolean) && <p className="px-5 pb-4 text-sm" style={muted}>{copy.empty}</p>}
        </Panel>
        <Panel title={copy.stages} subtitle={copy.breakdown}><OrderDonut rows={rows} total={data.active_orders} label={copy.total} />{!data.active_orders && <p className="px-5 pb-5 text-sm" style={muted}>{copy.noStages}</p>}</Panel>
      </div>
      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[minmax(300px,1fr)_minmax(0,2fr)]">
        <Panel title={copy.department} subtitle={`${copy.period} · ${t("field.qty")}`}><DepartmentBars labels={labels} values={stageKeys.map(k => data.totals[k])} title={copy.department} /><p className="border-t px-5 py-3 text-xs leading-5" style={{ ...muted, borderColor: "var(--erp-border-soft)" }}>{copy.note}</p></Panel>
        <section className="min-w-0 rounded-lg border" style={surface}>
          <div className="flex items-center justify-between gap-3 px-5 pt-5"><h2 className="text-base font-semibold">{copy.orders}</h2>{canOpenOrders && <a href="/production-orders" className="flex items-center gap-1 text-xs hover:underline">{copy.view}<ArrowRight size={14} /></a>}</div>
          <div className="flex flex-wrap gap-2 px-5 py-4"><div className="relative min-w-0 flex-1"><Search size={15} className="absolute left-3 top-3" style={muted} /><input className="input !pl-9" aria-label={copy.search} placeholder={copy.search} value={search} onChange={e => setSearch(e.target.value)} /></div><select className="input !w-auto max-w-full" aria-label={copy.type} value={kind} onChange={e => setKind(e.target.value)}><option value="all">{copy.all}</option><option value="client_order">{copy.client}</option><option value="branded_stock">{copy.branded}</option><option value="service_order">{copy.service}</option></select></div>
          <div className="max-h-[310px] overflow-auto"><table className="w-full text-left text-sm"><thead className="sticky top-0" style={{ background: "var(--erp-surface-muted)", ...muted }}><tr>{[copy.number, copy.type, copy.quantity, copy.status, copy.deadline].map(h => <th key={h} className="whitespace-nowrap px-5 py-2.5 text-xs font-normal">{h}</th>)}</tr></thead><tbody>
            {orders.map(o => <tr key={o.id} className="border-t" style={{ borderColor: "var(--erp-border-soft)" }}><td className="whitespace-nowrap px-5 py-3 font-semibold">{orderHref(o) ? <a className="hover:underline" href={orderHref(o)!}>{o.order_no}</a> : o.order_no}</td><td className="whitespace-nowrap px-5 py-3" style={muted}>{typeLabel(o.type)}</td><td className="px-5 py-3 tabular-nums">{n(o.qty)}</td><td className="whitespace-nowrap px-5 py-3"><span className="mr-2 inline-block h-2 w-2 rounded-sm" style={{ background: colors[statusOrder.indexOf(o.status)] }} />{stageLabel(o.status)}</td><td className="whitespace-nowrap px-5 py-3 tabular-nums" style={muted}>{o.deadline ? new Date(o.deadline).toLocaleDateString(lang === "en" ? "en-GB" : lang === "ru" ? "ru-RU" : "uz-UZ", { timeZone: "Asia/Tashkent", day: "2-digit", month: "short" }) : copy.noDeadline}</td></tr>)}
            {!orders.length && <tr><td colSpan={5} className="p-6 text-center" style={muted}>{copy.none}</td></tr>}
          </tbody></table></div>
          <p className="border-t px-5 py-3 text-xs" style={{ ...muted, borderColor: "var(--erp-border-soft)" }}>{data.active_orders > data.orders_limit ? copy.limited : `${orders.length} / ${data.active_orders} ${copy.total}`}</p>
        </section>
      </div>
      <details className="mt-4 rounded-lg border" style={surface}><summary className="cursor-pointer px-5 py-3 text-sm">{copy.details}</summary><div className="max-h-72 overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th className="px-5 py-2">{copy.period}</th>{labels.map(label => <th key={label} className="px-5 py-2">{label}</th>)}</tr></thead><tbody>{data.daily.map(p => <tr key={p.date}><th className="px-5 py-2 font-normal">{p.date}</th>{stageKeys.map(k => <td key={k} className="px-5 py-2 tabular-nums">{n(p[k])}</td>)}</tr>)}</tbody></table></div></details>
      <div className="mt-3 text-xs" style={muted}>{copy.updated} {new Date(data.updated_at).toLocaleTimeString(lang, { timeZone: data.timezone })} · Asia/Tashkent</div>
    </>}
    {can(me, "finance.view") && <section className="mt-5 flex flex-wrap items-center gap-x-10 gap-y-3 rounded-lg border px-5 py-4" style={surface}><h2 className="text-sm font-semibold">{copy.finance}</h2>{financeError ? <span className="text-sm" role="status">{copy.financeError}</span> : [ [copy.revenue, finance?.revenue_total], [copy.payments, finance?.payments_received] ].map(([label, value]) => <div key={String(label)} className="text-sm"><span style={muted}>{label}</span><span className="ml-4 font-semibold tabular-nums">{value === undefined ? "—" : `$${n(Number(value))}`}</span></div>)}</section>}
  </div>;
}
