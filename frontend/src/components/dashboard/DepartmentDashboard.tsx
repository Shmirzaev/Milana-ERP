"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ArrowLeft, ArrowRight, ImageIcon, Maximize2, Minimize2, RefreshCw } from "lucide-react";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { departmentMessages } from "./departmentMessages";
import { businessDate } from "./types";

type Totals = { bundles: number; pieces: number; orders: number; work_orders: number };
type FactoryBalance = { factory: string; bundles: number; pieces: number; orders: number; created_bundles: number; created_pieces: number; transferred_bundles: number; transferred_pieces: number };
type Cutting = { totals: Totals; factories: FactoryBalance[]; waste: { unit: string; records: number; quantity: number }[]; updated_at: string };
type PrintRow = { production_order_id: number; order_no: string; production_batch_id: number | null; batch_label?: string | null; model_code: string | null; model_image_url: string | null; print_image_url: string | null; bundles: number; pieces: number; deadline: string | null };
type Printing = { totals: Totals; rows: PrintRow[]; total: number; has_more: boolean; updated_at: string };
type Warehouse = { inventory_packages: number; inventory_pieces: number; inventory_models: number; shipment_count: number; shipped_packages: number; shipped_pieces: number; hot_products: { model_id: number | null; model_code: string | null; model_image_url: string | null; shipped_pieces: number }[]; updated_at: string };
type Mode = "cutting" | "printing" | "warehouse";
const names: Record<string, string> = { MIL: "Milana", BST: "Besttex", ECO: "Eco Cotton" };
const format = (value: number | undefined) => value === undefined ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: 4 });

function Picture({ src, label, empty, fitted = false }: { src: string | null; label: string; empty: string; fitted?: boolean }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return <div className={`flex items-center justify-center overflow-hidden rounded-md border border-[#e3dfd3] bg-white ${fitted ? "min-h-0 flex-1" : "aspect-[4/3] min-h-32"}`}>
    {src && !failed ? <img src={src} alt={label} className={`h-full w-full object-contain p-2 ${fitted ? "min-h-0" : "max-h-[240px]"}`} onError={() => setFailed(true)} />
      : <div className="flex flex-col items-center gap-2 p-4 text-center text-sm text-[#8a8472]"><ImageIcon aria-hidden size={24} />{empty}</div>}
  </div>;
}

function Metric({ label, value, note, accent = false, compact = false }: { label: string; value: number | undefined; note: string; accent?: boolean; compact?: boolean }) {
  return <div className={`min-w-0 rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] ${compact ? "p-2.5" : "p-5"}`}>
    <div className={`${compact ? "text-xs" : "text-sm"} text-[#6c6556]`}>{label}</div><div className={`break-words font-semibold tracking-tight tabular-nums ${compact ? "mt-1 text-2xl xl:text-3xl" : "mt-2 text-4xl xl:text-5xl"} ${accent ? "text-[#c2410c]" : "text-[#211c13]"}`}>{format(value)}</div>
    <div className={`${compact ? "mt-1 text-[10px]" : "mt-3 text-xs"} text-[#8a8472]`}>{note}</div>
  </div>;
}

function useMonitorColumns() {
  const [columns, setColumns] = useState(1);
  useEffect(() => {
    const medium = window.matchMedia("(min-width: 1000px)");
    const wide = window.matchMedia("(min-width: 1700px)");
    const update = () => setColumns(wide.matches ? 4 : medium.matches ? 2 : 1);
    update();
    medium.addEventListener("change", update);
    wide.addEventListener("change", update);
    return () => { medium.removeEventListener("change", update); wide.removeEventListener("change", update); };
  }, []);
  return columns;
}

export default function DepartmentDashboard({ mode }: { mode: Mode }) {
  const { lang } = useT();
  const c = departmentMessages[lang];
  const params = useSearchParams();
  const department = params.get("cutting_department") === "ECT" ? "ECT" : "CUT";
  const [big, setBig] = useState(false);
  const [period, setPeriod] = useState("week");
  const [anchor, setAnchor] = useState(businessDate);
  const [today, setToday] = useState(businessDate);
  const [page, setPage] = useState(0);
  const [auto, setAuto] = useState(false);
  const [grade, setGrade] = useState("ALL");
  const screenColumns = useMonitorColumns();
  const monitor = big && mode !== "cutting";
  const pageSize = big ? screenColumns : 8;
  useEffect(() => { setPage(0); }, [screenColumns]);
  useEffect(() => {
    const timer = setInterval(() => { const next = businessDate(); if (anchor === today) setAnchor(next); setToday(next); }, 60_000);
    return () => clearInterval(timer);
  }, [anchor, today]);
  useEffect(() => { const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setBig(false); setAuto(false); setPage(0); } }; window.addEventListener("keydown", escape); return () => window.removeEventListener("keydown", escape); }, []);
  const day = new Date(`${anchor}T12:00:00Z`);
  if (period === "week") day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7);
  if (period === "month") day.setUTCDate(1);
  const start = day.toISOString().slice(0, 10);
  const range = `start=${start}&end=${anchor}`;
  const url = mode === "printing" ? `/api/dashboard/printing?offset=${page * pageSize}&limit=${pageSize}`
    : mode === "cutting" ? `/api/dashboard/cutting?${range}&cutting_department_code=${department}`
      : `/api/dashboard/warehouse?${range}&stock_kind=${grade}`;
  const { data, error, isLoading, isValidating, mutate } = useSWR<Cutting | Printing | Warehouse>(url, fetcher, { refreshInterval: 30_000, keepPreviousData: false });
  const cutting = mode === "cutting" ? data as Cutting | undefined : undefined;
  const printing = mode === "printing" ? data as Printing | undefined : undefined;
  const warehouse = mode === "warehouse" ? data as Warehouse | undefined : undefined;
  const pages = Math.max(1, Math.ceil((printing?.total || 0) / pageSize));
  useEffect(() => { if (printing && page >= pages) setPage(pages - 1); }, [printing, page, pages]);
  useEffect(() => { if (!auto || pages < 2) return; const timer = setInterval(() => setPage(value => (value + 1) % pages), 20_000); return () => clearInterval(timer); }, [auto, pages]);
  const title = c[mode];
  return <div data-department-dashboard={mode} className={monitor ? "fixed inset-0 z-[80] flex h-dvh min-h-0 flex-col overflow-hidden bg-[#f4f1e8] p-3 lg:p-5" : big ? "fixed inset-0 z-[80] overflow-y-auto bg-[#f4f1e8] p-5 md:p-8" : "mx-auto max-w-[1900px] pb-6"}>
    <header className={`flex shrink-0 flex-wrap items-start justify-between border-b border-[#d9d2c0] ${monitor ? "mb-3 gap-2 pb-2" : "mb-6 gap-4 pb-5"}`}>
      <div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#786f5c]"><span className={`h-2 w-2 rounded-full ${error ? "bg-amber-600" : "bg-green-700"}`} />{error ? c.stale : c.live} · MILANA ERP</div>
        <h1 className={`${monitor ? "text-2xl" : "text-3xl xl:text-4xl"} font-semibold tracking-tight text-[#211c13]`}>{title}</h1>
        <p className={`${monitor ? "mt-1 text-xs" : "mt-2 text-sm"} text-[#6c6556]`}>{c[`${mode}Help`]}</p>
        {mode === "cutting" && <p className="mt-2 font-medium">{department === "ECT" ? "Eco Cotton" : "Milana"} · {c.cuttingDept}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn" disabled={isValidating} onClick={() => void mutate()} aria-label={c.refresh}><RefreshCw size={16} className={isValidating ? "animate-spin" : ""} />{c.refresh}</button>
        <button className="btn btn-primary" aria-pressed={big} onClick={() => { setBig(value => !value); setPage(0); if (big) setAuto(false); }}>{big ? <Minimize2 size={16} /> : <Maximize2 size={16} />}{big ? c.exit : c.screen}</button>
      </div>
    </header>
    <div className={`flex shrink-0 flex-wrap items-end justify-between ${monitor ? "mb-3 gap-2" : "mb-5 gap-4"}`}>
      {mode !== "printing" ? <div className="flex flex-wrap items-end gap-3">
        <div role="group" aria-label={c.period} className="flex rounded-lg border border-[#d9d2c0] bg-[#fdfcf8] p-1">
          {(["today", "week", "month"] as const).map(key => <button key={key} className={`rounded-md px-4 py-2 text-sm ${period === key ? "bg-[#211c13] text-white" : "text-[#6c6556]"}`} aria-pressed={period === key} onClick={() => setPeriod(key)}>{c[key]}</button>)}
        </div>
        <label className="text-xs text-[#6c6556]">{c.end}<input className="input mt-1 block w-auto" type="date" value={anchor} max={today} onChange={event => { if (/^\d{4}-\d{2}-\d{2}$/.test(event.target.value)) setAnchor(event.target.value); }} /></label>
        <span className="pb-2 text-sm tabular-nums text-[#6c6556]">{start} — {anchor}</span>
        {mode === "warehouse" && <label className="text-xs text-[#6c6556]">{c.grade}<select className="input mt-1 block w-auto" value={grade} onChange={event => setGrade(event.target.value)}><option value="ALL">{c.allGrades}</option>{(["standard", "first_grade", "second_grade"] as const).map(key => <option key={key} value={key}>{c[key]}</option>)}</select></label>}
      </div> : <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={auto} onChange={event => { setAuto(event.target.checked); if (event.target.checked && !big) { setBig(true); setPage(0); } }} />{c.auto}</label>}
      <div className="text-xs text-[#8a8472]">{c.timezone}{data?.updated_at && <span className="ml-3">{c.updated} {new Date(data.updated_at).toLocaleTimeString(lang, { timeZone: "Asia/Tashkent" })}</span>}</div>
    </div>
    {error && <div role="alert" className="mb-5 rounded-md border border-amber-500 bg-amber-50 p-4 text-amber-900">{data ? c.stale : c.error} <button className="ml-3 underline" onClick={() => void mutate()}>{c.refresh}</button></div>}
    {isLoading && !data && <p role="status" className="mb-5 text-[#6c6556]">{c.loading}</p>}
    {mode === "cutting" && <>
      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label={c.bundles} value={cutting?.totals.bundles} note={c.current} accent /><Metric label={c.pieces} value={cutting?.totals.pieces} note={c.current} />
        <Metric label={c.orders} value={cutting?.totals.orders} note={c.current} /><Metric label={c.works} value={cutting?.totals.work_orders} note={c.current} />
      </div>
      <section className="mb-5 overflow-x-auto rounded-lg border border-[#e3dfd3] bg-[#fdfcf8]">
        <div className="p-5"><h2 className="text-xl font-semibold">{c.factory}</h2><p className="mt-2 text-sm text-[#6c6556]">{c.balanceHelp}</p></div>
        <table className="table min-w-[750px]"><thead><tr><th>{c.factory}</th><th>{c.current} · {c.bundles}</th><th>{c.current} · {c.pieces}</th><th>{c.orders}</th><th>{c.created} · {c.period}</th><th>{c.transferred} · {c.period}</th></tr></thead>
          <tbody>{cutting?.factories.map(row => <tr key={row.factory}><td className="font-semibold"><Link className="hover:underline" href={`/cutting-inventory?cutting_department=${department}&destination_factory=${row.factory}`}>{names[row.factory] || c.unassigned}</Link></td><td className="text-2xl font-semibold tabular-nums">{format(row.bundles)}</td><td className="text-2xl font-semibold tabular-nums">{format(row.pieces)}</td><td>{format(row.orders)}</td><td>{format(row.created_bundles)} {c.bundles} / {format(row.created_pieces)} {c.pieces}</td><td>{format(row.transferred_bundles)} {c.bundles} / {format(row.transferred_pieces)} {c.pieces}</td></tr>)}</tbody></table>
      </section>
      <section className="rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] p-5"><h2 className="text-xl font-semibold">{c.waste}</h2><p className="mt-2 text-sm text-[#6c6556]">{c.wasteHelp}</p>
        <div className="mt-5 flex flex-wrap gap-8">{cutting?.waste.map(row => <div key={row.unit}><div className="text-4xl font-semibold tabular-nums">{format(row.quantity)} <span className="text-xl text-[#6c6556]">{row.unit}</span></div><p className="mt-2 text-xs text-[#8a8472]">{row.records} {c.records}</p></div>)}{cutting && !cutting.waste.length && <p>{c.noWaste}</p>}</div>
      </section><Link className="btn mt-5" href={`/cutting-inventory?cutting_department=${department}`}>{c.inventory}<ArrowRight size={16} /></Link>
    </>}
    {mode === "printing" && <>
      <div className={`grid shrink-0 gap-3 ${monitor ? "mb-3 grid-cols-3" : "mb-5 sm:grid-cols-3"}`}><Metric label={c.ready} value={printing?.totals.bundles} note={c.current} accent compact={monitor} /><Metric label={c.readyPieces} value={printing?.totals.pieces} note={c.current} compact={monitor} /><Metric label={c.readyOrders} value={printing?.totals.orders} note={c.current} compact={monitor} /></div>
      <div className={`grid ${monitor ? "min-h-0 flex-1 gap-3" : "gap-4 md:grid-cols-2 min-[1700px]:grid-cols-4"}`} style={monitor ? { gridTemplateColumns: `repeat(${screenColumns}, minmax(0, 1fr))`, gridTemplateRows: "minmax(0, 1fr)" } : undefined}>{printing?.rows.map(row => <article key={`${row.production_order_id}-${row.production_batch_id}-${row.model_code}`} className={`rounded-lg border border-[#d9d2c0] bg-[#fdfcf8] ${monitor ? "flex min-h-0 flex-col overflow-hidden p-3" : "p-4"}`}>
        <div className={`${monitor ? "mb-2" : "mb-3"} flex shrink-0 flex-wrap items-center justify-between gap-2`}><Link href={`/production-orders/${row.production_order_id}`} className={`${monitor ? "min-w-0 truncate text-base" : "text-lg"} font-semibold hover:underline`} title={row.order_no}>{row.order_no}</Link><span className="rounded bg-[#f4e5cf] px-2 py-1 text-sm font-semibold">{format(row.pieces)} {c.pieces}</span></div>
        <h2 className={`${monitor ? "mb-2 truncate text-lg" : "mb-3 text-xl"} shrink-0 font-semibold`}>{row.model_code || c.model}</h2>
        {row.batch_label && <p className={`${monitor ? "mb-2 truncate text-xs" : "mb-3 text-sm"} shrink-0 text-[#6c6556]`}>{row.batch_label}</p>}
        <div className={`grid grid-cols-2 gap-3 ${monitor ? "min-h-0 flex-1" : ""}`}><div className={monitor ? "flex min-h-0 flex-col" : undefined}><p className="mb-1 shrink-0 text-xs text-[#8a8472]">{c.model}</p><Picture src={row.model_image_url} label={`${c.model} ${row.model_code || ""}`} empty={c.noImage} fitted={monitor} /></div><div className={monitor ? "flex min-h-0 flex-col" : undefined}><p className="mb-1 shrink-0 text-xs text-[#8a8472]">{c.artwork}</p><Picture src={row.print_image_url} label={`${c.artwork} ${row.model_code || ""}`} empty={c.noArt} fitted={monitor} /></div></div>
        <div className={`${monitor ? "mt-2 text-xs" : "mt-3 text-sm"} flex shrink-0 flex-wrap justify-between gap-2 text-[#6c6556]`}><span>{format(row.bundles)} {c.bundles}</span>{row.deadline && <span>{c.deadline}: {new Date(row.deadline).toLocaleDateString(lang, { timeZone: "Asia/Tashkent" })}</span>}</div>
      </article>)}</div>
      {printing && !printing.total && <div className="card p-10 text-center text-lg">{c.noReady}</div>}
      {printing && pages > 1 && <div className={`${monitor ? "mt-3" : "mt-5"} flex shrink-0 items-center justify-center gap-4`}><button className="btn" disabled={page === 0} onClick={() => setPage(value => value - 1)}><ArrowLeft size={16} />{c.previous}</button><span>{c.page} {page + 1} {c.of} {pages}</span><button className="btn" disabled={!printing.has_more} onClick={() => setPage(value => value + 1)}>{c.next}<ArrowRight size={16} /></button></div>}
    </>}
    {mode === "warehouse" && <>
      <div className={`mb-3 grid shrink-0 gap-3 ${monitor ? "grid-cols-3 min-[1000px]:grid-cols-6" : "sm:grid-cols-2 xl:grid-cols-3 min-[1800px]:grid-cols-6"}`}>
        <Metric label={c.stock} value={warehouse?.inventory_pieces} note={c.current} accent compact={monitor} /><Metric label={c.packs} value={warehouse?.inventory_packages} note={c.current} compact={monitor} /><Metric label={c.models} value={warehouse?.inventory_models} note={c.current} compact={monitor} />
        <Metric label={c.shipments} value={warehouse?.shipment_count} note={c.period} compact={monitor} /><Metric label={c.shippedPieces} value={warehouse?.shipped_pieces} note={c.period} compact={monitor} /><Metric label={c.shippedPacks} value={warehouse?.shipped_packages} note={c.period} compact={monitor} />
      </div>{!monitor && <p className="mb-6 text-sm text-[#6c6556]">{c.stockHelp}</p>}
      <h2 className={`${monitor ? "text-lg" : "text-2xl"} shrink-0 font-semibold`}>{c.hot}</h2><p className={`${monitor ? "mb-2 mt-1 text-xs" : "mb-5 mt-2 text-sm"} shrink-0 text-[#6c6556]`}>{c.hotHelp}</p>
      <div className={`grid ${monitor ? "min-h-0 flex-1 auto-rows-fr grid-cols-2 gap-2 min-[800px]:grid-cols-4 min-[1200px]:grid-cols-8" : "gap-4 sm:grid-cols-2 xl:grid-cols-4"}`}>{warehouse?.hot_products.slice(0, 8).map((row, index) => <article key={row.model_id ?? "unknown"} className={`rounded-lg border border-[#d9d2c0] bg-[#fdfcf8] ${monitor ? "flex min-h-0 flex-col overflow-hidden p-2" : "p-4"}`}><div className={`${monitor ? "mb-2" : "mb-3"} flex shrink-0 items-center justify-between gap-2`}><span className="text-sm font-semibold text-[#c2410c]">#{index + 1}</span><h3 className={`truncate font-semibold ${monitor ? "text-xs" : "text-lg"}`} title={row.model_code || c.unassigned}>{row.model_code || c.unassigned}</h3></div><Picture src={row.model_image_url} label={row.model_code || c.model} empty={c.noImage} fitted={monitor} /><div className={`${monitor ? "mt-2 text-xl" : "mt-3 text-3xl"} shrink-0 font-semibold tabular-nums`}>{format(row.shipped_pieces)} <span className={`${monitor ? "block text-[10px]" : "text-sm"} font-normal text-[#6c6556]`}>{c.shippedPieces}</span></div></article>)}</div>
      {warehouse && !warehouse.hot_products.length && <div className="card p-10 text-center">{c.noHot}</div>}
      <Link href="/warehouse-stock" className={`btn shrink-0 ${monitor ? "mt-2 self-start" : "mt-5"}`}>{c.stockLink}<ArrowRight size={16} /></Link>
    </>}
  </div>;
}
