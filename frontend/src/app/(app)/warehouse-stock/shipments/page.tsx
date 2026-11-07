"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { Download, Search } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { can, useMe } from "@/lib/auth";
import { fetcher, fetchResponse } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { shipmentReportText } from "@/lib/shipmentReportText";
import { formatVariantNumber } from "@/lib/variantDisplay";
import { formatOrderReference } from "@/lib/orderRef";

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
    <PageHeader title={text.title} subtitle={text.subtitle} actions={<Link className="btn" href="/warehouse-stock">{text.back}</Link>} />
    {!me ? <p>{t("common.loading")}</p> : !allowed ? <p role="alert">{t("auth.accessDenied")}</p> : <>
      <form className="card mb-4 flex flex-wrap items-end gap-3 p-4" onSubmit={event => { event.preventDefault(); setFilters({ ...draft }); setPage(1); }}>
        <label className="min-w-[200px] flex-1"><span className="label">{text.search}</span><input className="input" value={draft.q} maxLength={140} onChange={event => setDraft(previous => ({ ...previous, q: event.target.value }))} /></label>
        <label><span className="label">{text.from}</span><input className="input" type="date" value={draft.from} max={draft.to || undefined} onChange={event => setDraft(previous => ({ ...previous, from: event.target.value }))} /></label>
        <label><span className="label">{text.to}</span><input className="input" type="date" value={draft.to} min={draft.from || undefined} onChange={event => setDraft(previous => ({ ...previous, to: event.target.value }))} /></label>
        <button type="submit" className="btn btn-primary"><Search className="h-4 w-4" />{text.apply}</button>
        <button type="button" className="btn" disabled={busy || isLoading || Boolean(error)} onClick={() => void download()}><Download className="h-4 w-4" />{busy ? t("common.loading") : text.download}</button>
      </form>
      {(error || downloadError) && <p role="alert" className="mb-4 text-red-700">{downloadError || error?.message}</p>}
      {data && <p className="mb-3 text-sm">{text.total}: <strong>{data.quantity.toLocaleString()}</strong> {text.quantity.toLocaleLowerCase()} · {data.package_count.toLocaleString()} {text.packages.toLocaleLowerCase()} · {data.shipment_count} {text.shipment.toLocaleLowerCase()}</p>}
      <div className="card overflow-x-auto"><table className="table min-w-[1150px]">
        <thead><tr>{[text.model, text.variant, text.quantity, text.packages, text.packageInfo, text.sizes, text.color, text.order, text.customer, text.shipped, text.shipment].map(label => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>
          {isLoading && <tr><td colSpan={11}>{t("common.loading")}</td></tr>}
          {data?.rows.map((row, index) => <tr key={`${row.shipment_id}-${index}`}>
            <td><div className="mono font-semibold">{row.model || "—"}</div><div className="max-w-48 whitespace-normal text-xs text-[#6f6a5b]">{row.description}</div></td>
            <td className="mono">{formatVariantNumber(row.variant) || "—"}</td><td className="tabular-nums">{row.quantity.toLocaleString()}</td><td>{row.packages.length}</td>
            <td className="max-w-64 whitespace-normal">{row.packages.map(pack => <div key={pack.package_no} className="text-xs">{pack.package_no}: {pack.quantity}</div>)}</td>
            <td>{Object.entries(row.sizes).map(([size, qty]) => <div key={size} className="whitespace-nowrap">{size}: {qty}</div>)}</td>
            <td>{row.color || "—"}</td><td className="mono">{formatOrderReference(row.order_no || "—")}</td><td>{row.customer || "—"}</td>
            <td className="whitespace-nowrap">{new Date(row.shipped_at.endsWith("Z") || /[+-]\d\d:\d\d$/.test(row.shipped_at) ? row.shipped_at : `${row.shipped_at}Z`).toLocaleString(lang === "ru" ? "ru-RU" : lang === "uz" ? "uz-UZ" : "en-GB", { timeZone: "Asia/Tashkent" })}</td>
            <td>{can(me, "storage.shipment") ? <Link className="underline" href={`/shipments?shipment_id=${row.shipment_id}`}>{row.shipment_no}</Link> : row.shipment_no}{row.historical_reconstruction && <div className="mt-1 text-xs text-[#6f6a5b]">{text.legacy}</div>}</td>
          </tr>)}
          {!isLoading && !error && !data?.rows.length && <tr><td colSpan={11} className="py-10 text-center">{text.empty}</td></tr>}
        </tbody>
      </table></div>
      {data && <div className="mt-4 flex items-center justify-end gap-3"><button className="btn" disabled={page <= 1 || isLoading} onClick={() => setPage(value => value - 1)}>{text.previous}</button><span className="text-sm">{page} / {Math.max(1, Math.ceil(data.total / data.page_size))}</span><button className="btn" disabled={page * data.page_size >= data.total || isLoading} onClick={() => setPage(value => value + 1)}>{text.next}</button></div>}
    </>}
  </div>;
}
