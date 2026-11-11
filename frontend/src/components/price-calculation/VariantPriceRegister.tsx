"use client";
import { useMemo, useState } from "react";
import useSWRInfinite from "swr/infinite";
import { api, fetcher, fetchResponse } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { priceWorkflowMessages } from "@/lib/priceWorkflowMessages";
import type { PriceCalculationRequest } from "@/lib/priceCalculationRequests";
import { formatVariantNumber } from "@/lib/variantDisplay";
import PriceRequestPagination from "./PriceRequestPagination";
import PriceCostDetails from "./PriceCostDetails";

type Row = { model_id: number; model_no: string; variant_no: string; model_name: string; selling_price: number | null; currency: string | null; source: string | null; price_updated_at: string | null; pending_factory: string | null; request: PriceCalculationRequest | null };
export default function VariantPriceRegister({ q, catalog }: { q: string; catalog: "standard" | "usluga" }) {
  const { lang } = useT(); const m = priceWorkflowMessages(lang);
  const [filter, setFilter] = useState("all");
  const params = new URLSearchParams({ q, catalog_scope: catalog, status: filter });
  const { data: pages, error, isLoading, size, setSize } = useSWRInfinite<Row[]>((index, previous: Row[] | null) => {
    if (previous && previous.length < 50) return null;
    return `/api/price-calculation/report?${params}&limit=50${index && previous ? `&before_id=${previous[previous.length - 1].model_id}` : ""}`;
  }, fetcher, { persistSize: false, revalidateFirstPage: true });
  const rows = useMemo(() => (pages || []).flat(), [pages]);
  const [history, setHistory] = useState<{ title: string; rows: PriceCalculationRequest[] } | null>(null);
  const [message, setMessage] = useState(""); const [downloading, setDownloading] = useState(false);
  async function download() {
    setMessage(""); setDownloading(true);
    try {
      const response = await fetchResponse(`/api/price-calculation/report.xlsx?${params}`, { credentials: "include" });
      if (!response.ok) throw new Error(m.error);
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement("a");
      link.href = url; link.download = "variant-prices.xlsx"; link.click(); URL.revokeObjectURL(url);
    } catch (err) { setMessage(err instanceof Error ? err.message : m.error); }
    finally { setDownloading(false); }
  }
  async function showHistory(row: Row) {
    setMessage("");
    try { setHistory({ title: `${row.model_no} / ${formatVariantNumber(row.variant_no)}`, rows: await api.get<PriceCalculationRequest[]>(`/api/price-calculation/models/${row.model_id}/history`) }); }
    catch (err) { setMessage(err instanceof Error ? err.message : m.error); }
  }
  return <div>
    <div className="mb-3 flex flex-wrap justify-between gap-3"><select className="input w-52" aria-label={m.report} value={filter} onChange={event => setFilter(event.target.value)}><option value="all">{m.all}</option><option value="pending">{m.pending}</option><option value="approval">{m.approval}</option><option value="priced">{m.priced}</option></select><button className="btn" disabled={downloading} onClick={download}>{m.export}</button></div>
    {isLoading ? <p>{m.loading}</p> : null}{error || message ? <p role="alert" className="text-sm text-red-700">{message || m.error}</p> : null}
    <div className="overflow-x-auto rounded-lg border border-[var(--erp-border)]"><table className="w-full text-sm"><thead><tr>{[m.model, m.variant, m.name, m.existing, m.source, m.pending, m.history].map(label => <th key={label} className="whitespace-nowrap px-3 py-3 text-left font-semibold">{label}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.model_id} className="border-t border-[var(--erp-border)]"><td className="px-3 py-3"><a className="underline" href={`/models/${row.model_id}`}>{row.model_no}</a></td><td className="px-3">{formatVariantNumber(row.variant_no)}</td><td className="px-3">{row.model_name}</td><td className="whitespace-nowrap px-3 tabular-nums">{row.selling_price === null ? "—" : `${new Intl.NumberFormat(lang, { maximumFractionDigits: 4 }).format(row.selling_price)} ${row.currency || ""}`}</td><td className="px-3">{row.source || "—"}</td><td className="px-3">{row.request ? m[row.request.workflow_state] : row.pending_factory ? `${m.owner}: ${row.pending_factory}` : row.selling_price ? "—" : m.noRequest}</td><td className="px-3"><div className="flex gap-2 py-2"><button className="btn" onClick={() => showHistory(row)}>{m.history}</button></div></td></tr>)}</tbody></table></div>
    {!isLoading && !error && !rows.length ? <p className="mt-3 text-sm">{m.empty}</p> : null}
    <PriceRequestPagination hasMore={pages?.[pages.length - 1]?.length === 50} isLoadingMore={size > (pages?.length || 0)} loadMore={() => void setSize(value => value + 1)} />
    {history ? <section className="mt-5 rounded-lg border border-[var(--erp-border)] p-4"><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">{m.history}: {history.title}</h2><button className="btn" onClick={() => setHistory(null)}>{m.close}</button></div>{history.rows.length ? history.rows.map(request => <div key={request.id} className="border-t border-[var(--erp-border)] py-4"><p className="mb-2 text-sm font-semibold">{request.kroy_no || "—"} · {m[request.workflow_state]}</p><PriceCostDetails request={request} /></div>) : <p>{m.empty}</p>}</section> : null}
  </div>;
}
