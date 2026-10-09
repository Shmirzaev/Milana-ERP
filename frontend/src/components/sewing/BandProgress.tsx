"use client";
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { sewingBandText, type BandJob } from "@/lib/sewingBandText";

export default function BandProgress({ jobs, manager = false, refresh, onOutput }: {
  jobs: BandJob[]; manager?: boolean; refresh?: () => void; onOutput?: (job: BandJob) => void;
}) {
  const { lang } = useT(); const text = sewingBandText(lang);
  const [finishJob, setFinishJob] = useState<BandJob | null>(null);
  const [reason, setReason] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const active = jobs.filter(j => !j.line_finished);
  const finished = jobs.filter(j => j.line_finished);
  function row(job: BandJob) {
    return <div key={job.id} className="space-y-2 border-t border-stone-200 py-3">
      {manager ? <Link className="font-medium underline" href={`/work-orders/${job.work_order_id}/sewing`}>{job.order_no}</Link>
        : <button className="text-left font-medium underline" onClick={() => onOutput?.(job)}>{job.order_no}</button>}
      <p className="text-sm">{job.model} {job.batch ? `· ${job.batch}` : ""}</p>
      <p className="text-sm tabular-nums">{text.reported}: {job.reported_qty} / {job.quantity} · {Math.min(100, Math.round(100 * job.reported_qty / Math.max(1, job.quantity)))}%</p>
      <progress className="h-2 w-full accent-stone-700" aria-label={`${job.order_no} ${text.reported}`} value={Math.min(job.reported_qty, job.quantity)} max={Math.max(1, job.quantity)} />
      {job.top_qty !== job.bottom_qty && <p className="text-sm">{text.top}: {job.top_qty} · {text.bottom}: {job.bottom_qty}</p>}
      <p className="text-sm">{text.remaining}: {Math.max(0, job.quantity - job.reported_qty)} · {text.actual}: {job.actual_qty}</p>
      {!!job.actual_defective_qty && <p className="text-sm">{text.failed}: {job.actual_defective_qty}</p>}
      {job.awaiting_final && <p className="text-sm font-medium">{text.finalPending}</p>}
      {job.finish_reason && <p className="text-sm">{text.reason}: {job.finish_reason}</p>}
      {onOutput && job.status !== "completed" && <button className="btn" onClick={() => onOutput(job)}>{text.final}</button>}
      {manager && job.status !== "completed" && (!job.line_finished || job.finish_reason) && <button className="btn" onClick={() => { setFinishJob(job); setReason(""); setError(""); }}>{job.finish_reason ? text.reopen : text.finish}</button>}
    </div>;
  }
  return <div>
    {!active.length && <p className="py-4 font-medium">{text.available}</p>}
    {active.map(row)}
    {!!finished.length && <details className="border-t border-stone-200 py-3"><summary className="cursor-pointer">{text.history} ({finished.length})</summary>{finished.map(row)}</details>}
    {finishJob && <form className="space-y-2 border-t border-stone-300 py-3" onSubmit={async e => {
      e.preventDefault(); if (busy) return; setBusy(true); setError("");
      try { await api.post(`/api/sewing-bands/${finishJob.id}/finish`, { reason, finished: !finishJob.finish_reason }); setFinishJob(null); refresh?.(); }
      catch (err) { setError(String(err)); } finally { setBusy(false); }
    }}>
      <label className="block">{text.finishReason}<input className="input mt-1 w-full" value={reason} onChange={e => setReason(e.target.value)} required maxLength={255} /></label>
      <p className="text-sm">{text.finishHint}</p>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <button className="btn" disabled={busy}>{finishJob.finish_reason ? text.reopen : text.finish}</button>{" "}
      <button className="btn" type="button" disabled={busy} onClick={() => setFinishJob(null)}>{text.cancel}</button>
    </form>}
  </div>;
}
