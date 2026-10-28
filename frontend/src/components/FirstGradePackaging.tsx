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
import { gradePackageWeights, type PackagingGrade } from "@/lib/gradePackageWeights";

export type PackagingSizeBalance = { needs_size_entry: boolean; total: number; version: string;
  sizes: { size: string; accepted: number | null; packed: number; remaining: number }[] };
export default function FirstGradePackaging({ productionOrderId, batchId, modelId, color, onChanged }: {
  productionOrderId: number; batchId?: number; modelId: number; color: string; onChanged: () => Promise<unknown>;
}) {
  return <GradePackaging key={`${productionOrderId}:${batchId ?? ""}:${modelId}:${color}`}
    productionOrderId={productionOrderId} batchId={batchId} modelId={modelId} color={color} onChanged={onChanged} />;
}

function GradePackaging({ productionOrderId, batchId, modelId, color, onChanged }: {
  productionOrderId: number; batchId?: number; modelId: number; color: string; onChanged: () => Promise<unknown>;
}) {
  const { lang } = useT(); const copy = firstGradeText[lang]; const { me } = useMe();
  const [grade, setGrade] = useState<PackagingGrade>("first_grade");
  const [weights, setWeights] = useState<Record<PackagingGrade, string>>({ first_grade: "", second_grade: "" });
  const [open, setOpen] = useState(false); const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState(""); const [run, setRun] = useState<PackagePrintRun | null>(null);
  const path = "/api/packages/print-runs/create-packages";
  const sizePath = `/api/packages/first-grade/size-entry/${productionOrderId}${batchId ? `?production_batch_id=${batchId}` : ""}`;
  const { data, error, mutate } = useSWR<PackagingSizeBalance>(open ? sizePath : null, fetcher);
  if (!can(me, "packaging.packages")) return null;
  const total = Object.values(quantities).reduce((a, b) => a + b, 0);
  let validWeight = false;
  try { gradePackageWeights(grade, data?.sizes.map(row => ({ size: row.size, quantity: quantities[row.size] || 0 })) || [], weights[grade]); validWeight = true; } catch { /* Incomplete form. */ }
  return <section className="card p-3">
    <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>{copy.title} / {copy.second}</button>
    {open && <><div className="mt-3 flex flex-wrap items-end gap-3">
      <label className="block text-sm">{copy.grade}<select className="input mt-1 !w-auto" aria-label={copy.grade} value={grade} disabled={busy} onChange={e => { setGrade(e.target.value as PackagingGrade); setQuantities({}); setMessage(""); setRun(null); }}><option value="first_grade">{copy.title}</option><option value="second_grade">{copy.second}</option></select></label>
      {(["first_grade", "second_grade"] as const).map(kind => <label key={kind} className="block text-sm">{kind === "first_grade" ? copy.firstTotalWeight : copy.secondTotalWeight}
        <input className="input mt-1 !w-36" type="number" min="0.0001" max="9999999999.9999" step="0.0001" inputMode="decimal"
          aria-label={kind === "first_grade" ? copy.firstTotalWeight : copy.secondTotalWeight} disabled={busy}
          value={weights[kind]} onChange={e => setWeights({ ...weights, [kind]: e.target.value })} />
      </label>)}
    </div>
      <details className="my-2 text-xs text-[#56503f]"><summary className="cursor-pointer">{copy.help}</summary><p className="mt-1 max-w-3xl">{grade === "first_grade" ? copy.description : copy.secondHelp} {copy.totalWeightHelp}</p></details>
      <PendingPackageWorkflow path={path} onResolved={async () => { await mutate(); await onChanged(); }} />
      {error && <p role="alert" className="text-red-700">{error.message}</p>}
      {!data && !error && <p>{copy.loading}</p>}
      {data?.needs_size_entry && <PackagingSizeEntry key={data.version} data={data} path={sizePath} onSaved={async () => { setQuantities({}); await mutate(); }} />}
      {data && !data.needs_size_entry && <form onSubmit={async e => {
        e.preventDefault(); if (!me || busy || !validWeight || total < 1 || (grade === "first_grade" && total > 200)) return;
        setBusy(true); setMessage("");
        try {
          const packages = gradePackageWeights(grade, data.sizes.map(row => ({ size: row.size, quantity: quantities[row.size] || 0 })), weights[grade]).map(row => ({
              production_order_id: productionOrderId, production_batch_id: batchId || null,
              model_id: modelId, color, stock_kind: grade, capacity: row.quantity,
              weight_kg: row.weight_kg,
              items: [{ model_id: modelId, color, size: row.size, quantity: row.quantity }],
            }));
          const result = await postPackageWorkflow<PackagePrintRun>(path, { packages }, me.id);
          setRun(result); setQuantities({}); setWeights({ ...weights, [grade]: "" }); setMessage(grade === "first_grade" ? copy.saved : copy.secondSaved); await mutate(); await onChanged();
        } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
        finally { setBusy(false); }
      }}>
        <div className="max-w-3xl overflow-x-auto"><table className="w-full text-sm [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_td]:px-2 [&_td]:py-1.5 [&_tr]:border-b [&_tr]:border-[#ecebe3]"><thead><tr><th>{copy.size}</th><th>{copy.accepted}</th><th>{copy.packed}</th><th>{copy.remaining}</th><th>{copy.count}</th></tr></thead><tbody>
          {data.sizes.map(row => <tr key={row.size}><td>{row.size}</td><td>{row.accepted}</td><td>{row.packed}</td><td>{row.remaining}</td><td><input className="input !w-24 !py-1" type="number" min="0" max={grade === "first_grade" ? Math.min(200, row.remaining) : row.remaining} step="1" aria-label={`${copy.quantity} ${row.size}`} value={quantities[row.size] || ""} disabled={busy} onChange={e => setQuantities({ ...quantities, [row.size]: Math.max(0, Math.floor(Number(e.target.value))) })} /></td></tr>)}
        </tbody></table></div>
        <p className="mt-2 text-sm">{copy.total}: {total} · {weights[grade] || "0"} kg</p>
        <button className="btn btn-primary mt-2" disabled={busy || !validWeight || total < 1 || (grade === "first_grade" && total > 200)}>{grade === "first_grade" ? copy.create : copy.createPacks} ({total}{grade === "first_grade" ? "/200" : ""})</button>
      </form>}
      {message && <p role="status" className="mt-3">{message}</p>}
      {run && <button type="button" className="btn mt-3" onClick={async () => { try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } }}>{copy.print}</button>}
    </>}
  </section>;
}
