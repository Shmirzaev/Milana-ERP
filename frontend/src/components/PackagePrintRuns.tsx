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

export default function PackagePrintRuns({ productionOrderId, refreshKey = 0 }: { productionOrderId?: number; refreshKey?: number }) {
  const { lang } = useT();
  const { me } = useMe();
  const dialogs = useDialogs();
  const [deleting, setDeleting] = useState<number | null>(null);
  const [selectedRun, setSelectedRun] = useState<PackagePrintRun | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const copy = packageWorkflowCopy[lang];
  const path = `/api/packages/print-runs${productionOrderId ? `?production_order_id=${productionOrderId}` : ""}`;
  const { data, error, mutate } = useSWR<PackagePrintRun[]>([path, refreshKey], ([url]: [string, number]) => fetcher(url));
  const [printError, setPrintError] = useState("");
  return <section className="mt-4 border-t pt-4">
    <h3 className="mb-3 font-medium">{copy.runs}</h3>
    {(error || printError) && <p role="alert" className="text-red-700">{printError || error.message}</p>}
    {!data && !error && <p>{copy.loading}</p>}
    {data?.length === 0 && <p>{copy.empty}</p>}
    {!!data?.length && <div className="overflow-x-auto"><table className="table text-sm"><thead><tr>
      <th>{copy.runs}</th><th>{copy.packages}</th><th>{copy.pieces}</th><th>{copy.status}</th><th>{copy.reprint}</th>
    </tr></thead><tbody>{data.map(run => <tr key={run.id}>
      <td>{run.run_no}<div className="text-xs text-slate-500">{new Date(run.created_at).toLocaleString(lang)}</div></td>
      <td>{run.count}</td><td>{run.quantity}</td><td>{run.received_at ? copy.complete : copy.pending}</td>
      <td><button type="button" className="btn" onClick={async () => {
        setPrintError("");
        try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); }
        catch (e: any) { setPrintError(e.message); }
      }}>{copy.reprint}</button>{run.manual_receipt && can(me, "storage.packages") && <button type="button" className="btn ml-2" disabled={deleting !== null} onClick={() => { setSelectedRun(run); setSelectedIds([]); }}>{copy.deletePacks}</button>}</td>
    </tr>)}</tbody></table></div>}
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
          await mutate();
          await mutateCache(key => typeof key === "string" && (key.startsWith("/api/packages") || key.startsWith("/api/finished-goods")));
        } catch (e: any) { setPrintError(e.message); }
        finally { setDeleting(null); }
      }}>{copy.deletePacks} ({selectedIds.length})</button></div>
    </Modal>
  </section>;
}
