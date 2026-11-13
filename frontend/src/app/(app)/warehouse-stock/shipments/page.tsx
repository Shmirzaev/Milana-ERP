"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { can, useMe } from "@/lib/auth";
import { fetcher, fetchResponse } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { shipmentReportText } from "@/lib/shipmentReportText";
import { formatVariantNumber } from "@/lib/variantDisplay";
import { formatOrderReference } from "@/lib/orderRef";
import { shipmentReportDates } from "@/lib/shipmentReportDates";

type ReportRow = {
  shipment_id: number; shipment_no: string; shipped_at: string; status: string;
  order_no: string; customer: string; model: string; variant: string; description: string;
  color: string; quantity: number; packages: Array<{ package_no: string; quantity: number }>;
  sizes: Record<string, number>; historical_reconstruction: boolean;
};
type Report = { rows: ReportRow[]; total: number; quantity: number; package_count: number; shipment_count: number; page: number; page_size: number };

export default function WarehouseShipmentReport() {
  const { lang, t } = useT();
  const text = shipmentReportText[lang];
  const locale = lang === "ru" ? "ru-RU" : lang === "uz" ? "uz-UZ" : "en-GB";
  const number = (value: number) => value.toLocaleString(locale);
  const shippedDate = (value: string) => new Date(value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  const { me } = useMe();
  const allowed = can(me, "storage.packages", "storage.shipment");
  const [draft, setDraft] = useState({ q: "", from: "", to: "" });
  const [filters, setFilters] = useState(draft);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const params = useMemo(() => {
    const result = new URLSearchParams();
    if (filters.q) result.set("q", filters.q);
    if (filters.from) result.set("date_from", filters.from);
    if (filters.to) result.set("date_to", filters.to);
    return result;
  }, [filters]);
  const { data, error, isLoading } = useSWR<Report>(allowed ? `/api/warehouse-reports/shipments?${params}&page=${page}` : null, fetcher);
  function applyPeriod(period: "day" | "month") {
    const next = { q: draft.q.trim(), ...shipmentReportDates(period) };
    setDraft(next); setFilters(next); setPage(1);
  }
  async function download() {
    setBusy(true); setDownloadError("");
    try {
      const response = await fetchResponse(`/api/warehouse-reports/shipments.xlsx?${params}&lang=${lang}`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : text.error);
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = "warehouse-shipments.xlsx";
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) { setDownloadError(failure instanceof Error ? failure.message : text.error); }
    finally { setBusy(false); }
  }
  return <div>
    <PageHeader title={text.title} subtitle={text.subtitle} actions={<>
      <Link className="btn" href="/warehouse-stock"><ArrowLeft className="h-4 w-4" />{text.back}</Link>
      {allowed && <button type="button" className="btn btn-primary" disabled={busy || isLoading || Boolean(error) || !data?.rows.length} onClick={() => void download()}><Download className="h-4 w-4" />{busy ? t("common.loading") : text.download}</button>}
    </>} />
    {!me ? <p>{t("common.loading")}</p> : !allowed ? <p role="alert">{t("auth.accessDenied")}</p> : <>
      <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label={text.period}>
        <span className="mr-1 text-sm text-[#56503f]">{text.period}</span>
        <button type="button" className="btn" onClick={() => applyPeriod("day")}>{text.today}</button>
        <button type="button" className="btn" onClick={() => applyPeriod("month")}>{text.thisMonth}</button>
      </div>
      <form className="mb-5 grid grid-cols-1 items-end gap-3 rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] p-4 sm:grid-cols-2 xl:grid-cols-[minmax(240px,1fr)_170px_170px_auto_auto]" onSubmit={event => { event.preventDefault(); setFilters({ ...draft, q: draft.q.trim() }); setPage(1); }}>
        <label className="sm:col-span-2 xl:col-span-1"><span className="mb-1.5 block text-sm text-[#56503f]">{text.search}</span><div className="relative"><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[#8a8472]" /><input className="input pl-9" placeholder={text.searchPlaceholder} value={draft.q} maxLength={140} onChange={event => setDraft(previous => ({ ...previous, q: event.target.value }))} /></div></label>
        <label><span className="mb-1.5 block text-sm text-[#56503f]">{text.from}</span><input className="input" type="date" value={draft.from} max={draft.to || undefined} onChange={event => setDraft(previous => ({ ...previous, from: event.target.value }))} /></label>
        <label><span className="mb-1.5 block text-sm text-[#56503f]">{text.to}</span><input className="input" type="date" value={draft.to} min={draft.from || undefined} onChange={event => setDraft(previous => ({ ...previous, to: event.target.value }))} /></label>
        <button type="submit" className="btn btn-primary"><Search className="h-4 w-4" />{text.apply}</button>
        <button type="button" className="btn" disabled={!draft.q && !draft.from && !draft.to && !filters.q && !filters.from && !filters.to} onClick={() => { const empty = { q: "", from: "", to: "" }; setDraft(empty); setFilters(empty); setPage(1); }}>{text.reset}</button>
      </form>
      {(error || downloadError) && <p role="alert" className="mb-4 text-red-700">{downloadError || error?.message}</p>}
      <section aria-label={text.title} className="overflow-hidden rounded-lg border border-[#e3dfd3] bg-[#fdfcf8]">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#e3dfd3] px-4 py-4">
        <div><h2 className="text-base font-semibold">{text.results}</h2><p className="mt-1 text-xs text-[#6f6a5b]">{text.tashkent}</p></div>
        {data && <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm tabular-nums">
          {[[text.quantity, data.quantity], [text.packages, data.package_count], [text.shipment, data.shipment_count]].map(([label, value]) => <div key={label}><dt className="text-xs text-[#6f6a5b]">{label}</dt><dd className="mt-0.5 text-lg font-semibold">{number(Number(value))}</dd></div>)}
        </dl>}
      </div>
      <div className="overflow-x-auto"><table className="w-full min-w-[1040px] text-left text-sm [&_th]:px-4 [&_th]:py-3 [&_th]:font-semibold [&_th]:text-[#56503f] [&_td]:px-4 [&_td]:py-4 [&_td]:align-top">
        <caption className="sr-only">{text.subtitle}</caption>
        <thead className="border-b border-[#e3dfd3] bg-[#f1efe8]"><tr>{[text.shipped, text.customer, text.model, text.variant, text.quantity, text.packageInfo, text.sizes, text.order].map((label, index) => <th scope="col" key={label} className={index === 4 ? "text-right" : ""}>{label}</th>)}</tr></thead>
        <tbody>
          {isLoading && <tr><td colSpan={8} className="text-center text-[#6f6a5b]">{t("common.loading")}</td></tr>}
          {data?.rows.map((row, index) => <tr className="border-b border-[#ecebe3] last:border-0 hover:bg-[#f7f5ef]" key={`${row.shipment_id}-${index}`}>
            <td className="whitespace-nowrap"><time dateTime={row.shipped_at}>{shippedDate(row.shipped_at).toLocaleDateString(locale, { timeZone: "Asia/Tashkent", day: "2-digit", month: "short", year: "numeric" })}</time><div className="mt-1 text-xs text-[#6f6a5b]">{shippedDate(row.shipped_at).toLocaleTimeString(locale, { timeZone: "Asia/Tashkent", hour: "2-digit", minute: "2-digit" })}</div><div className="mt-2 text-xs">{can(me, "storage.shipment") ? <Link className="underline decoration-[#c4bda9] underline-offset-2" href={`/shipments?shipment_id=${row.shipment_id}`}>{row.shipment_no}</Link> : row.shipment_no}</div>{row.historical_reconstruction && <div className="mt-1 max-w-36 whitespace-normal text-xs text-[#6f6a5b]">{text.legacy}</div>}</td>
            <td className="max-w-48 break-words">{row.customer || "—"}</td>
            <td><div className="mono font-semibold">{row.model || "—"}</div>{row.description && <div className="mt-1 max-w-48 whitespace-normal text-xs leading-5 text-[#6f6a5b]">{row.description}</div>}{row.color && <div className="mt-1 text-xs text-[#6f6a5b]">{text.color}: {row.color}</div>}</td>
            <td className="mono whitespace-nowrap">{formatVariantNumber(row.variant) || "—"}</td><td className="text-right font-semibold tabular-nums">{number(row.quantity)}</td>
            <td className="min-w-48"><div className="mb-2 text-xs text-[#6f6a5b]">{text.packages}: {number(row.packages.length)}</div>{row.packages.slice(0, 2).map(pack => <div key={pack.package_no} className="flex justify-between gap-4 text-xs leading-5"><span className="break-all">{pack.package_no}</span><span className="tabular-nums">{number(pack.quantity)}</span></div>)}{row.packages.length > 2 && <details className="mt-1"><summary className="cursor-pointer text-xs text-[#6f6a5b] underline underline-offset-2">{text.morePackages} ({number(row.packages.length - 2)})</summary>{row.packages.slice(2).map(pack => <div key={pack.package_no} className="mt-1 flex justify-between gap-4 text-xs"><span className="break-all">{pack.package_no}</span><span className="tabular-nums">{number(pack.quantity)}</span></div>)}</details>}</td>
            <td><div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-1 text-xs">{Object.entries(row.sizes).map(([size, qty]) => <div key={size} className="contents"><span className="whitespace-nowrap text-[#6f6a5b]">{size}</span><span className="text-right tabular-nums">{number(qty)}</span></div>)}</div></td>
            <td className="mono whitespace-nowrap">{formatOrderReference(row.order_no || "—")}</td>
          </tr>)}
          {!isLoading && !error && !data?.rows.length && <tr><td colSpan={8} className="h-40 text-center text-[#6f6a5b]">{text.empty}</td></tr>}
        </tbody>
      </table></div>
      {data && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e3dfd3] px-4 py-3"><span className="text-sm text-[#6f6a5b]">{text.rows}: {data.total ? number((page - 1) * data.page_size + 1) : 0}–{number(Math.min(page * data.page_size, data.total))} / {number(data.total)}</span><div className="flex items-center gap-3"><button className="btn" disabled={page <= 1 || isLoading} onClick={() => setPage(value => value - 1)}><ChevronLeft className="h-4 w-4" />{text.previous}</button><span className="text-sm tabular-nums">{number(page)} / {number(Math.max(1, Math.ceil(data.total / data.page_size)))}</span><button className="btn" disabled={page * data.page_size >= data.total || isLoading} onClick={() => setPage(value => value + 1)}>{text.next}<ChevronRight className="h-4 w-4" /></button></div></div>}
      </section>
    </>}
  </div>;
}
