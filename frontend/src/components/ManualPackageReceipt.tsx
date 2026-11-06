"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { packageWorkflowChangedEvent, packageWorkflowCopy, pendingPackageWorkflow, postPackageWorkflow, reconcilePendingPackageWorkflow, type PackagePrintRun } from "@/lib/packageWorkflow";
import ModelAsyncSelect from "@/components/ModelAsyncSelect";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";

export default function ManualPackageReceipt({ onCreated, packagingDepartment }: { onCreated: () => void; packagingDepartment?: string }) {
  const { me } = useMe();
  const { lang } = useT();
  const c = packageWorkflowCopy[lang];
  const packaging = !!packagingDepartment;
  const path = packaging ? "/api/packages/manual-packaging" : "/api/packages/manual-receipt";
  const title = packaging ? c.manualPackaging : c.manual;
  const modelInputId = packaging ? "manual-packaging-model" : "manual-package-model";
  const [open, setOpen] = useState(false);
  const [model, setModel] = useState<number | null>(null);
  const [sizes, setSizes] = useState<string[]>([]);
  const [quantities, setQuantities] = useState<string[]>([""]);
  const [color, setColor] = useState("");
  const [weight, setWeight] = useState("");
  const [count, setCount] = useState("1");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [result, setResult] = useState<{ receipt_no: string; print_run: PackagePrintRun } | null>(null);
  const modelRequest = useRef(0);
  const [pendingBody, setPendingBody] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    if (!me?.id) return;
    const update = () => {
      try {
        const saved = pendingPackageWorkflow(path, me.id);
        setPendingBody(saved?.body || null);
        if (!saved) return;
        const body = saved.body;
        setModel(body.model_id); setColor(body.color);
        setWeight(String(body.weight_kg)); setCount(String(body.count));
        setQuantities(body.pack_quantities?.map(String) || Array(body.count).fill(String((body.sizes || []).reduce((sum: number, row: any) => sum + row.quantity, 0))));
        setSizes((body.sizes || []).map((row: any) => row.size));
      } catch (caught: any) {
        setError(caught?.message || "Package recovery storage is unavailable");
      }
    };
    update();
    window.addEventListener(packageWorkflowChangedEvent, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(packageWorkflowChangedEvent, update);
      window.removeEventListener("storage", update);
    };
  }, [me?.id, path]);

  async function recoverPendingReceipt() {
    setBusy(true); setError(""); setNotice("");
    try {
      const reconciled = await reconcilePendingPackageWorkflow<{ receipt_no: string; print_run: PackagePrintRun }>(path, me!.id);
      setPendingBody(null);
      if (reconciled.status === "completed") {
        setResult(reconciled.result);
        onCreated();
      } else {
        setNotice(reconciled.status === "cancelled" ? c.pendingCancelled : c.resultUnavailable);
      }
    } catch (caught: any) {
      setError(caught?.message || "Package recovery failed");
      try {
        setPendingBody(pendingPackageWorkflow(path, me!.id)?.body || null);
      } catch {
        setPendingBody(null);
      }
    } finally {
      setBusy(false);
    }
  }

  const allowed = can(me, packaging ? "packaging.packages" : "storage.packages");
  if (!allowed) return (pendingBody || notice || error) ? <div className="my-3 border p-3">
    {pendingBody && <p role="status">{c.pendingRequest}</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {pendingBody && <button type="button" className="btn mt-2" disabled={busy} onClick={recoverPendingReceipt}>{busy ? c.loading : c.recover}</button>}
  </div> : null;
  const total = quantities.reduce((sum, value) => sum + Number(value || 0), 0);
  return <>
    <button className="btn" type="button" onClick={() => { setOpen(true); if (!packaging) setResult(null); }}>{title}</button>
    <Modal open={open} title={title} onClose={() => { if (!busy) setOpen(false); }} wide>
      <form onSubmit={async event => {
        event.preventDefault();
        setBusy(true); setError(""); setNotice("");
        try {
          const saved = await postPackageWorkflow<{ receipt_no: string; print_run: PackagePrintRun }>(path, pendingBody || {
            model_id: model, color, weight_kg: Number(weight), count: quantities.length,
            pack_quantities: quantities.map(Number),
            ...(packaging ? { packaging_department_code: packagingDepartment } : {}),
          }, me!.id);
          setPendingBody(null); setResult(saved); onCreated();
          if (packaging) {
            try { await api.openLabel(`/api/packages/print-runs/${saved.print_run.id}/label`); }
            catch (e: any) { setError(e.message); }
          }
        } catch (e: any) { setError(e.message); setPendingBody(pendingPackageWorkflow(path, me!.id)?.body || null); }
        finally { setBusy(false); }
      }} className="space-y-4">
        <p className="text-sm">{packaging ? c.packagingReview : c.review}</p>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {pendingBody && <p role="status">{c.pendingRequest}</p>}
        {result ? <div>
          <p role="status">{packaging ? c.packagingCreated : c.received}: {result.receipt_no} · {result.print_run.count} {c.packages} · {result.print_run.quantity} {c.pieces}</p>
          <button type="button" className="btn mt-3" onClick={async () => {
            try { await api.openLabel(`/api/packages/print-runs/${result.print_run.id}/label`); }
            catch (e: any) { setError(e.message); }
          }}>{c.reprint}</button>
          {packaging && <button type="button" className="btn ml-2 mt-3" onClick={() => { setResult(null); setError(""); setModel(null); setSizes([]); setColor(""); setWeight(""); setCount("1"); setQuantities([""]); }}>{c.createMore}</button>}
          {packaging && <button type="button" className="btn ml-2 mt-3" disabled={busy} onClick={() => setCancelling(true)}>{c.cancelPacks}</button>}
        </div> : <>
          {pendingBody && <button type="button" className="btn" disabled={busy} onClick={recoverPendingReceipt}>{c.cancelPending}</button>}
          <fieldset disabled={busy || !!pendingBody} className="space-y-4">
            <div><label className="label" htmlFor={modelInputId}>{c.model}</label>
              <ModelAsyncSelect value={model} status="approved" inputId={modelInputId} required disabled={busy || !!pendingBody}
                placeholder={c.model} noResultsText={c.none} loadingText={c.loading} loadMoreText={c.more}
                onChange={async id => {
                  const request = ++modelRequest.current;
                  setModel(id); setSizes([]); setLoading(true); setError("");
                  try {
                    const row = await api.get<any>(`/api/models/${id}`);
                    if (request === modelRequest.current) setSizes((row.sizes || []).map((s: any) => s.size));
                  } catch (e: any) { if (request === modelRequest.current) setError(e.message); }
                  finally { if (request === modelRequest.current) setLoading(false); }
                }} />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="label">{c.color}<input className="input" required maxLength={64} value={color} onChange={e => setColor(e.target.value)} /></label>
              <label className="label">{c.weight}<input className="input" required type="number" min="0.0001" step="0.0001" value={weight} onChange={e => setWeight(e.target.value)} /></label>
              <label className="label">{c.count}<input className="input" required type="number" min="1" max="200" step="1" value={count} onChange={e => { setCount(e.target.value); const n = Math.min(200, Math.max(1, Number(e.target.value) || 1)); setQuantities(previous => Array.from({ length: n }, (_, i) => previous[i] ?? "")); }} /></label>
            </div>
            {loading && <p>{c.loading}</p>}
            {!!sizes.length && <p className="text-sm">{c.size}: {sizes.join(" / ")}</p>}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{quantities.map((quantity, index) => <label className="label" key={index}>{c.packQuantity} {index + 1}
              <input className="input" required type="number" min="1" max="10000" step="1" value={quantity} onChange={e => setQuantities(previous => previous.map((value, i) => i === index ? e.target.value : value))} />
            </label>)}</div>
            <p>{quantities.length} {c.packages} · {total} {c.pieces}</p>
          </fieldset>
          <button type="submit" className="btn btn-primary" disabled={busy || loading || !model || quantities.some(value => !Number.isInteger(Number(value)) || Number(value) <= 0)}>{busy ? c.loading : pendingBody ? c.retry : packaging ? c.packagingSave : c.save}</button>
        </>}
        <button type="button" className="btn ml-2" disabled={busy} onClick={() => setOpen(false)}>{c.cancel}</button>
      </form>
    </Modal>
    <ConfirmDialog isOpen={cancelling} title={c.cancelPacks} message={c.cancelPacksConfirm} onCancel={() => { if (!busy) setCancelling(false); }} onConfirm={async () => {
      if (busy) return;
      if (!result) return;
      setBusy(true); setError("");
      try {
        await api.del(`/api/packages/manual-packaging/${result.print_run.id}`);
        setResult(null); setNotice(c.packsCancelled); setCancelling(false); onCreated();
      } catch (e: any) { setError(e.message); setCancelling(false); }
      finally { setBusy(false); }
    }} />
  </>;
}
