"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { firstGradeText } from "@/lib/firstGradeText";
import { postPackageWorkflow, type PackagePrintRun } from "@/lib/packageWorkflow";
import PendingPackageWorkflow from "@/components/PendingPackageWorkflow";
import PackagingSizeEntry from "@/components/PackagingSizeEntry";

export type PackagingSizeBalance = { needs_size_entry: boolean; total: number; version: string;
  sizes: { size: string; accepted: number | null; packed: number; remaining: number }[] };
export default function FirstGradePackaging({ productionOrderId, batchId, modelId, color, onChanged }: {
  productionOrderId: number; batchId?: number; modelId: number; color: string; onChanged: () => Promise<unknown>;
}) {
  const { lang } = useT(); const copy = firstGradeText[lang]; const { me } = useMe();
  const [grade, setGrade] = useState<"first_grade" | "second_grade">("first_grade");
  const [weights, setWeights] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(false); const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState(""); const [run, setRun] = useState<PackagePrintRun | null>(null);
  const path = "/api/packages/print-runs/create-packages";
  const sizePath = `/api/packages/first-grade/size-entry/${productionOrderId}${batchId ? `?production_batch_id=${batchId}` : ""}`;
  const { data, error, mutate } = useSWR<PackagingSizeBalance>(open ? sizePath : null, fetcher);
  if (!can(me, "packaging.packages")) return null;
  const total = Object.values(quantities).reduce((a, b) => a + b, 0);
  return <section className="card p-4">
    <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>{copy.title} / {copy.second}</button>
    {open && <><label className="label mt-3">{copy.grade}<select className="input" aria-label={copy.grade} value={grade} disabled={busy} onChange={e => { setGrade(e.target.value as typeof grade); setQuantities({}); setWeights({}); }}><option value="first_grade">{copy.title}</option><option value="second_grade">{copy.second}</option></select></label>
      <p className="my-3 text-sm text-slate-600">{grade === "first_grade" ? copy.description : copy.secondHelp}</p>
      <PendingPackageWorkflow path={path} onResolved={async () => { await mutate(); await onChanged(); }} />
      {error && <p role="alert" className="text-red-700">{error.message}</p>}
      {!data && !error && <p>{copy.loading}</p>}
      {data?.needs_size_entry && <PackagingSizeEntry key={data.version} data={data} path={sizePath} onSaved={async () => { setQuantities({}); await mutate(); }} />}
      {data && !data.needs_size_entry && <form onSubmit={async e => {
        e.preventDefault(); if (!me || busy || total < 1 || (grade === "first_grade" && total > 200)) return;
        setBusy(true); setMessage("");
        try {
          const packages = data.sizes.flatMap(row => {
            const count = quantities[row.size] || 0;
            if (!count) return [];
            const units = Math.round(Number(weights[row.size]) * 10000);
            if (!Number.isFinite(units) || units <= 0) throw new Error(copy.weight);
            const piecesPerPackage = grade === "first_grade" ? 1 : count;
            const packageCount = grade === "first_grade" ? count : 1;
            return Array.from({ length: packageCount }, (_, index) => ({
              production_order_id: productionOrderId, production_batch_id: batchId || null,
              model_id: modelId, color, stock_kind: grade, capacity: piecesPerPackage,
              weight_kg: (Math.floor(units / packageCount) + (index < units % packageCount ? 1 : 0)) / 10000,
              items: [{ model_id: modelId, color, size: row.size, quantity: piecesPerPackage }],
            }));
          });
          const result = await postPackageWorkflow<PackagePrintRun>(path, { packages }, me.id);
          setRun(result); setQuantities({}); setWeights({}); setMessage(grade === "first_grade" ? copy.saved : copy.secondSaved); await mutate(); await onChanged();
        } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
        finally { setBusy(false); }
      }}>
        <div className="overflow-x-auto"><table className="table text-sm"><thead><tr><th>{copy.size}</th><th>{copy.accepted}</th><th>{copy.packed}</th><th>{copy.remaining}</th><th>{copy.count}</th><th>{copy.weight}</th></tr></thead><tbody>
          {data.sizes.map(row => <tr key={row.size}><td>{row.size}</td><td>{row.accepted}</td><td>{row.packed}</td><td>{row.remaining}</td><td><input className="input w-28" type="number" min="0" max={grade === "first_grade" ? Math.min(200, row.remaining) : row.remaining} step="1" aria-label={`${copy.quantity} ${row.size}`} value={quantities[row.size] || ""} disabled={busy} onChange={e => setQuantities({ ...quantities, [row.size]: Math.max(0, Math.floor(Number(e.target.value))) })} /></td><td><input className="input w-28" type="number" min="0.0001" step="0.0001" required={Boolean(quantities[row.size])} disabled={busy || !quantities[row.size]} aria-label={`${copy.weight} ${row.size}`} value={weights[row.size] || ""} onChange={e => setWeights({ ...weights, [row.size]: e.target.value })} /></td></tr>)}
        </tbody></table></div>
        <button className="btn btn-primary mt-3" disabled={busy || total < 1 || (grade === "first_grade" && total > 200)}>{grade === "first_grade" ? copy.create : copy.createPacks} ({total}{grade === "first_grade" ? "/200" : ""})</button>
      </form>}
      {message && <p role="status" className="mt-3">{message}</p>}
      {run && <button type="button" className="btn mt-3" onClick={async () => { try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } }}>{copy.print}</button>}
    </>}
  </section>;
}
