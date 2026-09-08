"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { packageWorkflowCopy, pendingPackageWorkflow, postPackageWorkflow, type PackagePrintRun } from "@/lib/packageWorkflow";
import ModelAsyncSelect from "@/components/ModelAsyncSelect";
import Modal from "@/components/Modal";

export default function ManualPackageReceipt({ onCreated }: { onCreated: () => void }) {
  const { me } = useMe();
  const { lang } = useT();
  const c = packageWorkflowCopy[lang];
  const [open, setOpen] = useState(false);
  const [model, setModel] = useState<number | null>(null);
  const [sizes, setSizes] = useState<Array<{ size: string; quantity: string }>>([]);
  const [color, setColor] = useState("");
  const [weight, setWeight] = useState("");
  const [count, setCount] = useState("1");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{ receipt_no: string; print_run: PackagePrintRun } | null>(null);
  const modelRequest = useRef(0);
  const [pendingBody, setPendingBody] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    if (!me?.id) return;
    const saved = pendingPackageWorkflow("/api/packages/manual-receipt", me.id);
    if (!saved) return;
    const body = saved.body;
    setPendingBody(body); setModel(body.model_id); setColor(body.color);
    setWeight(String(body.weight_kg)); setCount(String(body.count)); setReason(body.reason);
    setSizes(body.sizes.map((row: any) => ({ size: row.size, quantity: String(row.quantity) })));
  }, [me?.id]);
  if (!can(me, "storage.packages")) return null;
  const total = sizes.reduce((sum, row) => sum + Number(row.quantity || 0), 0);
  return <>
    <button className="btn" type="button" onClick={() => { setOpen(true); setResult(null); }}>{c.manual}</button>
    <Modal open={open} title={c.manual} onClose={() => { if (!busy) setOpen(false); }} wide>
      <form onSubmit={async event => {
        event.preventDefault();
        setBusy(true); setError("");
        try {
          const saved = await postPackageWorkflow<{ receipt_no: string; print_run: PackagePrintRun }>("/api/packages/manual-receipt", pendingBody || {
            model_id: model, color, weight_kg: Number(weight), count: Number(count), reason,
            sizes: sizes.filter(row => Number(row.quantity) > 0).map(row => ({ size: row.size, quantity: Number(row.quantity) })),
          }, me!.id);
          setPendingBody(null); setResult(saved); onCreated();
        } catch (e: any) { setError(e.message); setPendingBody(pendingPackageWorkflow("/api/packages/manual-receipt", me!.id)?.body || null); }
        finally { setBusy(false); }
      }} className="space-y-4">
        <p className="text-sm">{c.review}</p>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        {pendingBody && <p role="status">{c.pendingRequest}</p>}
        {result ? <div>
          <p role="status">{c.received}: {result.receipt_no} · {result.print_run.count} {c.packages} · {result.print_run.quantity} {c.pieces}</p>
          <button type="button" className="btn mt-3" onClick={async () => {
            try { await api.openLabel(`/api/packages/print-runs/${result.print_run.id}/label`); }
            catch (e: any) { setError(e.message); }
          }}>{c.reprint}</button>
        </div> : <>
          <fieldset disabled={busy || !!pendingBody} className="space-y-4">
            <div><label className="label" htmlFor="manual-package-model">{c.model}</label>
              <ModelAsyncSelect value={model} status="approved" inputId="manual-package-model" required disabled={busy || !!pendingBody}
                placeholder={c.model} noResultsText={c.none} loadingText={c.loading} loadMoreText={c.more}
                onChange={async id => {
                  const request = ++modelRequest.current;
                  setModel(id); setSizes([]); setLoading(true); setError("");
                  try {
                    const row = await api.get<any>(`/api/models/${id}`);
                    if (request === modelRequest.current) setSizes((row.sizes || []).map((s: any) => ({ size: s.size, quantity: "0" })));
                  } catch (e: any) { if (request === modelRequest.current) setError(e.message); }
                  finally { if (request === modelRequest.current) setLoading(false); }
                }} />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="label">{c.color}<input className="input" required maxLength={64} value={color} onChange={e => setColor(e.target.value)} /></label>
              <label className="label">{c.weight}<input className="input" required type="number" min="0.0001" step="0.0001" value={weight} onChange={e => setWeight(e.target.value)} /></label>
              <label className="label">{c.count}<input className="input" required type="number" min="1" max="200" step="1" value={count} onChange={e => setCount(e.target.value)} /></label>
            </div>
            <div><p className="label">{c.sizes}</p>{loading && <p>{c.loading}</p>}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{sizes.map((row, i) => <label className="label" key={row.size}>{row.size}
                <input className="input" type="number" min="0" step="1" value={row.quantity} onChange={e => setSizes(previous => previous.map((s, index) => index === i ? { ...s, quantity: e.target.value } : s))} />
              </label>)}</div>
            </div>
            <label className="label">{c.reason}<textarea className="input" required minLength={3} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /></label>
            <p>{Number(count) || 0} {c.packages} · {total * (Number(count) || 0)} {c.pieces}</p>
          </fieldset>
          <button type="submit" className="btn btn-primary" disabled={busy || loading || !model || total <= 0}>{busy ? c.loading : pendingBody ? c.retry : c.save}</button>
        </>}
        <button type="button" className="btn ml-2" disabled={busy} onClick={() => setOpen(false)}>{c.cancel}</button>
      </form>
    </Modal>
  </>;
}
