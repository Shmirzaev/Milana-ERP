"use client";

import { useState, type FormEvent } from "react";
import { RefreshCw, Search } from "lucide-react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type UsageRow = {
  id: string;
  cutting_batch_no: string | number | null;
  cutting_date: string;
  production_no: string | null;
  order_no: string | null;
  model_code: string | null;
  model_name: string | null;
  item_sku: string | null;
  item_name: string;
  batch_no: string | null;
  internal_batch_no?: string | null;
  color: string | null;
  unit: string;
  quantity: number;
};
type UsageReport = {
  rows: UsageRow[];
  total: number;
  page: number;
  page_size: number;
  totals: { unit: string; quantity: number }[];
  cutting_department: string;
};
type Filters = { q: string; from: string; to: string };
const EMPTY_FILTERS: Filters = { q: "", from: "", to: "" };

export default function CuttingFabricUsagePage() {
  const { t, lang } = useT();
  const { me } = useMe();
  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const validDates = !draft.from || !draft.to || draft.from <= draft.to;
  const department = me?.factory_code === "ECO" ? "ECT" : "CUT";
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), cutting_department: department });
  if (filters.q) params.set("q", filters.q);
  if (filters.from) params.set("date_from", filters.from);
  if (filters.to) params.set("date_to", filters.to);
  const allowed = can(me, "storage.items", "storage.receive", "cutting.records", "planning.production");
  const { data, error, isLoading, isValidating, mutate } = useSWR<UsageReport>(
    allowed ? `/api/inventory/cutting-fabric-usage?${params}` : null,
    fetcher,
    { shouldRetryOnError: false },
  );
  const number = new Intl.NumberFormat(lang === "uz" ? "uz-UZ" : lang, { maximumFractionDigits: 3 });
  const date = new Intl.DateTimeFormat(lang === "uz" ? "uz-UZ" : lang, {
    timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit",
  });
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validDates) return;
    setFilters({ ...draft, q: draft.q.trim() });
    setPage(1);
  }
  function clear() {
    setDraft(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setPage(1);
  }
  const rows = data?.rows ?? [];
  const columns = ["date", "order", "cuttingBatch", "model", "fabric", "stockBatch", "color", "quantity"];
  return (
    <div>
      <PageHeader title={t("cuttingUsage.title")} subtitle={t("cuttingUsage.description")} />
      <section className="card overflow-hidden">
        <form onSubmit={apply} className="flex flex-wrap items-end gap-3 border-b border-[#e3dfd3] p-4">
          <div className="min-w-56 flex-1">
            <label htmlFor="cutting-usage-search" className="label">{t("cuttingUsage.search")}</label>
            <input id="cutting-usage-search" type="search" className="input w-full" value={draft.q}
              placeholder={t("cuttingUsage.searchHint")} onChange={(event) => setDraft({ ...draft, q: event.target.value })} />
          </div>
          <div>
            <label htmlFor="cutting-usage-from" className="label">{t("cuttingUsage.from")}</label>
            <input id="cutting-usage-from" type="date" className="input" value={draft.from} max={draft.to || undefined}
              onChange={(event) => setDraft({ ...draft, from: event.target.value })} />
          </div>
          <div>
            <label htmlFor="cutting-usage-to" className="label">{t("cuttingUsage.to")}</label>
            <input id="cutting-usage-to" type="date" className="input" value={draft.to} min={draft.from || undefined}
              onChange={(event) => setDraft({ ...draft, to: event.target.value })} />
          </div>
          <button className="btn btn-primary" type="submit" disabled={!validDates}>
            <Search className="h-4 w-4" aria-hidden="true" />{t("cuttingUsage.apply")}
          </button>
          <button className="btn" type="button" onClick={clear}>{t("cuttingUsage.clear")}</button>
          <button className="btn" type="button" disabled={isValidating} onClick={() => mutate()}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />{t("btn.refresh")}
          </button>
        </form>
        {!validDates && <p role="alert" className="px-4 pt-3 text-sm text-red-700">{t("cuttingUsage.invalidDates")}</p>}
        {error && <p role="alert" className="p-4 text-sm text-red-700">{t("cuttingUsage.loadError")}</p>}
        {isLoading && <p role="status" className="p-4 text-sm">{t("common.loading")}</p>}
        {!isLoading && !error && data && (
          <>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 p-4 text-sm" aria-live="polite">
              <span>{t("cuttingUsage.records", { count: data.total })}</span>
              {data.totals.map((total) => (
                <span key={total.unit}>{t("cuttingUsage.total")}: <strong className="font-semibold tabular-nums">{number.format(total.quantity)} {total.unit}</strong></span>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[960px] text-left text-sm">
                <thead className="border-y border-[#e3dfd3] bg-[#f8f7f2]">
                  <tr>{columns.map((column) => <th key={column} scope="col" className={`px-4 py-3 font-semibold ${column === "quantity" ? "text-right" : ""}`}>{t(`cuttingUsage.${column}`)}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-[#ecebe3]">
                  {rows.map((row) => (
                    <tr key={row.id} className="align-top">
                      <td className="whitespace-nowrap px-4 py-3">{row.cutting_date ? date.format(new Date(row.cutting_date)) : "—"}</td>
                      <td className="px-4 py-3">
                        <div>{row.production_no || row.order_no || "—"}</div>
                        {row.order_no && row.order_no !== row.production_no && <div className="mt-1 text-xs text-[#6d6758]">{row.order_no}</div>}
                      </td>
                      <td className="px-4 py-3">{row.cutting_batch_no ?? "—"}</td>
                      <td className="min-w-40 px-4 py-3"><div>{row.model_code || "—"}</div><div className="mt-1 whitespace-normal text-xs text-[#6d6758]">{row.model_name}</div></td>
                      <td className="min-w-48 px-4 py-3"><div className="whitespace-normal break-words">{row.item_name}</div><div className="mt-1 text-xs text-[#6d6758]">{row.item_sku}</div></td>
                      <td className="px-4 py-3">{row.batch_no || row.internal_batch_no || "—"}</td>
                      <td className="px-4 py-3">{row.color || "—"}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{number.format(row.quantity)} {row.unit}</td>
                    </tr>
                  ))}
                  {!rows.length && <tr><td colSpan={columns.length} className="p-8 text-center text-[#6d6758]">{t("cuttingUsage.empty")}</td></tr>}
                </tbody>
              </table>
            </div>
            <PaginationControls page={page} pageSize={pageSize} total={data.total} count={rows.length}
              onPageChange={setPage} onPageSizeChange={(size) => { setPageSize(size); setPage(1); }} pageSizeOptions={[25, 50, 100, 200]} />
          </>
        )}
      </section>
    </div>
  );
}
