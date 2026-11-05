"use client";
import Modal from "@/components/Modal";
import useSWR from "swr";
import { useT } from "@/lib/i18n";
import { api, fetcher } from "@/lib/api";
import { packageWorkflowCopy, type PackagePrintRun } from "@/lib/packageWorkflow";
import { can, useMe } from "@/lib/auth";
import { useDialogs } from "@/components/DialogProvider";
import { mutate as mutateCache } from "swr";
import { useState } from "react";
import { formatModelVariantCode } from "@/lib/variantDisplay";

export default function PackagePrintRuns({ productionOrderId, refreshKey = 0, standalone = false }: { productionOrderId?: number; refreshKey?: number; standalone?: boolean }) {
  const { lang, t } = useT();
  const { me } = useMe();
  const dialogs = useDialogs();
  const [deleting, setDeleting] = useState<number | null>(null);
  const [selectedRun, setSelectedRun] = useState<PackagePrintRun | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const copy = packageWorkflowCopy[lang];
  const [page, setPage] = useState(1);
  const emptyFilters = { q: "", created_from: "", created_to: "", receipt_status: "" as "" | "pending" | "received" };
  const [draft, setDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const [invalidDates, setInvalidDates] = useState(false);
  const pageSize = 50;
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (productionOrderId) query.set("production_order_id", String(productionOrderId));
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
  const path = `/api/packages/print-runs?${query}`;
  const { data: result, error, mutate, isValidating } = useSWR<{
    rows: PackagePrintRun[]; total: number; has_more: boolean;
  }>([path, refreshKey], ([url]: [string, number]) => fetcher(url), {
    onSuccess: value => {
      const lastPage = Math.max(1, Math.ceil(value.total / pageSize));
      if (page > lastPage) setPage(lastPage);
    },
  });
  const data = result?.rows;
  const [printError, setPrintError] = useState("");
  return <section className={standalone ? "" : "mt-4 border-t pt-4"}>
    {!standalone && <h3 className="mb-3 font-medium">{copy.runs}</h3>}
    <form className="mb-4 flex flex-wrap items-end gap-3" onSubmit={e => {
      e.preventDefault();
      if (draft.created_from && draft.created_to && draft.created_from > draft.created_to) {
        setInvalidDates(true); return;
      }
      setInvalidDates(false); setPage(1); setFilters({ ...draft, q: draft.q.trim() });
    }}>
      <label className="flex min-w-56 flex-1 flex-col gap-1 text-sm">{copy.searchRuns}
        <input className="input" type="search" maxLength={120} value={draft.q} onChange={e => setDraft({ ...draft, q: e.target.value })} />
      </label>
      <label className="flex flex-col gap-1 text-sm">{copy.dateFrom}
        <input className="input" type="date" value={draft.created_from} onChange={e => setDraft({ ...draft, created_from: e.target.value })} />
      </label>
      <label className="flex flex-col gap-1 text-sm">{copy.dateTo}
        <input className="input" type="date" value={draft.created_to} onChange={e => setDraft({ ...draft, created_to: e.target.value })} />
      </label>
      <label className="flex flex-col gap-1 text-sm">{copy.status}
        <select className="input" value={draft.receipt_status} onChange={e => setDraft({ ...draft, receipt_status: e.target.value as typeof draft.receipt_status })}>
          <option value="">{copy.allReceipts}</option><option value="pending">{copy.pending}</option><option value="received">{copy.complete}</option>
        </select>
      </label>
      <button type="submit" className="btn">{copy.search}</button>
      <button type="button" className="btn" onClick={() => {
        setDraft(emptyFilters); setFilters(emptyFilters); setPage(1); setInvalidDates(false);
      }}>{copy.resetFilters}</button>
    </form>
    {invalidDates && <p role="alert" className="mb-3 text-red-700">{copy.invalidDates}</p>}
    {(error || printError) && <p role="alert" className="text-red-700">{printError || error.message}</p>}
    {error && <button type="button" className="btn" onClick={() => void mutate()}>{t("common.retry")}</button>}
    {!data && !error && <p>{copy.loading}</p>}
    {data?.length === 0 && <p>{copy.noMatches}</p>}
    {!!data?.length && <div className="overflow-x-auto"><table className="table text-sm"><thead><tr>
      <th>{copy.runs}</th><th>{copy.model}</th><th>{copy.packages}</th><th>{copy.pieces}</th><th>{copy.status}</th><th>{copy.reprint}</th>
    </tr></thead><tbody>{data.map(run => <tr key={run.id}>
      <td>{run.run_no}<div className="text-xs text-slate-500">{new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(run.created_at) ? run.created_at : `${run.created_at}Z`).toLocaleString(lang, { timeZone: "Asia/Tashkent" })}</div></td>
      <td>{run.model_codes?.length ? run.model_codes.map(code => <div key={code}>{formatModelVariantCode(code)}</div>) : "—"}</td>
      <td>{run.count}</td><td>{run.quantity}</td><td>{run.received_at ? copy.complete : copy.pending}</td>
      <td><button type="button" className="btn" onClick={async () => {
        setPrintError("");
        try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); }
        catch (e: any) { setPrintError(e.message); }
      }}>{copy.reprint}</button>{run.manual_receipt && can(me, "storage.packages") && <button type="button" className="btn ml-2" disabled={deleting !== null} onClick={() => { setSelectedRun(run); setSelectedIds([]); }}>{copy.deletePacks}</button>}</td>
    </tr>)}</tbody></table></div>}
    {result && <nav aria-label={copy.runs} className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t py-3 text-sm">
      <span>{t("common.showingRange", { start: data?.length ? (page - 1) * pageSize + 1 : 0, end: data?.length ? (page - 1) * pageSize + data.length : 0, total: result.total })}</span>
      <div className="flex items-center gap-3">
        <button type="button" className="btn" disabled={page === 1 || isValidating} onClick={() => setPage(page - 1)}>{copy.previous}</button>
        <span>{copy.page} {page} / {Math.max(1, Math.ceil(result.total / pageSize))}</span>
        <button type="button" className="btn" disabled={!result.has_more || isValidating} onClick={() => setPage(page + 1)}>{copy.next}</button>
      </div>
    </nav>}
    <Modal open={!!selectedRun} onClose={() => { if (deleting === null) setSelectedRun(null); }} title={`${copy.deletePacks} · ${selectedRun?.run_no || ""}`}>
      <p className="mb-3 text-sm">{copy.deleteConfirm}</p>
      {printError && <p role="alert" className="mb-3 text-red-700">{printError}</p>}
      <label className="mb-3 flex gap-2"><input type="checkbox" disabled={deleting !== null} checked={!!selectedRun && selectedIds.length === selectedRun.packages.length} onChange={e => setSelectedIds(e.target.checked ? selectedRun!.package_ids : [])} />{copy.select} ({selectedRun?.count})</label>
      <div className="max-h-80 overflow-y-auto divide-y">{selectedRun?.packages.map(pkg => <label key={pkg.id} className="flex gap-3 py-2 text-sm"><input type="checkbox" disabled={deleting !== null} checked={selectedIds.includes(pkg.id)} onChange={e => setSelectedIds(ids => e.target.checked ? [...ids, pkg.id] : ids.filter(id => id !== pkg.id))} /><span className="flex-1">{pkg.package_no}</span><span>{pkg.quantity} {copy.pieces}</span></label>)}</div>
      <div className="mt-4 flex justify-end gap-2"><button type="button" className="btn" disabled={deleting !== null} onClick={() => setSelectedRun(null)}>{copy.cancel}</button><button type="button" className="btn" disabled={!selectedIds.length || deleting !== null} onClick={async () => {
        if (!selectedRun || !(await dialogs.ask({ message: `${selectedRun.run_no} · ${selectedIds.length} ${copy.packages}. ${copy.deleteConfirm}` }))) return;
        setDeleting(selectedRun.id); setPrintError("");
        try {
          const query = new URLSearchParams(selectedIds.map(id => ["package_ids", String(id)]));
          await api.del(`/api/packages/print-runs/${selectedRun.id}/manual-packages?${query}`);
          setSelectedRun(null); setSelectedIds([]);
          const updated = await mutate();
          if (page > 1 && updated?.rows.length === 0) setPage(page - 1);
          await mutateCache(key => typeof key === "string" && (key.startsWith("/api/packages") || key.startsWith("/api/finished-goods")));
        } catch (e: any) { setPrintError(e.message); }
        finally { setDeleting(null); }
      }}>{copy.deletePacks} ({selectedIds.length})</button></div>
    </Modal>
  </section>;
}
