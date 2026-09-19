"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { firstGradeText } from "@/lib/firstGradeText";
import { postPackageWorkflow, type PackagePrintRun } from "@/lib/packageWorkflow";
import PendingPackageWorkflow from "@/components/PendingPackageWorkflow";

type Balance = { sizes: { size: string; accepted: number; packed: number; remaining: number }[] };
export default function FirstGradePackaging({ productionOrderId, batchId, modelId, color, onChanged }: {
  productionOrderId: number; batchId?: number; modelId: number; color: string; onChanged: () => Promise<unknown>;
}) {
  const { lang } = useT(); const copy = firstGradeText[lang]; const { me } = useMe();
  const [open, setOpen] = useState(false); const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState(""); const [run, setRun] = useState<PackagePrintRun | null>(null);
  const path = "/api/packages/print-runs/create-packages";
  const { data, error, mutate } = useSWR<Balance>(open ? `/api/packages/first-grade/balance/${productionOrderId}${batchId ? `?production_batch_id=${batchId}` : ""}` : null, fetcher);
  if (!can(me, "packaging.packages")) return null;
  const total = Object.values(quantities).reduce((a, b) => a + b, 0);
  return <section className="card p-4">
    <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>{copy.title}</button>
    {open && <><p className="my-3 text-sm text-slate-600">{copy.description}</p>
      <PendingPackageWorkflow path={path} onResolved={async () => { await mutate(); await onChanged(); }} />
      {error && <p role="alert" className="text-red-700">{error.message}</p>}
      {!data && !error && <p>{copy.loading}</p>}
      {data && <form onSubmit={async e => {
        e.preventDefault(); if (!me || busy || total < 1 || total > 200) return;
        setBusy(true); setMessage("");
        try {
          const packages = data.sizes.flatMap(row => Array.from({ length: quantities[row.size] || 0 }, () => ({
            production_order_id: productionOrderId, production_batch_id: batchId || null,
            model_id: modelId, color, stock_kind: "first_grade", capacity: 1,
            items: [{ model_id: modelId, color, size: row.size, quantity: 1 }],
          })));
          const result = await postPackageWorkflow<PackagePrintRun>(path, { packages }, me.id);
          setRun(result); setQuantities({}); setMessage(copy.saved); await mutate(); await onChanged();
        } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
        finally { setBusy(false); }
      }}>
        <div className="overflow-x-auto"><table className="table text-sm"><thead><tr><th>{copy.size}</th><th>{copy.accepted}</th><th>{copy.packed}</th><th>{copy.remaining}</th><th>{copy.quantity}</th></tr></thead><tbody>
          {data.sizes.map(row => <tr key={row.size}><td>{row.size}</td><td>{row.accepted}</td><td>{row.packed}</td><td>{row.remaining}</td><td><input className="input w-28" type="number" min="0" max={Math.min(200, row.remaining)} step="1" aria-label={`${copy.quantity} ${row.size}`} value={quantities[row.size] || ""} disabled={busy} onChange={e => setQuantities({ ...quantities, [row.size]: Math.max(0, Math.floor(Number(e.target.value))) })} /></td></tr>)}
        </tbody></table></div>
        <button className="btn btn-primary mt-3" disabled={busy || total < 1 || total > 200}>{copy.create} ({total}/200)</button>
      </form>}
      {message && <p role="status" className="mt-3">{message}</p>}
      {run && <button type="button" className="btn mt-3" onClick={async () => { try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } }}>{copy.print}</button>}
    </>}
  </section>;
}
