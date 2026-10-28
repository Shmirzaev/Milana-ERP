"use client";
import { useRef, useState } from "react";
import Modal from "@/components/Modal";
import DefectReasonSelect from "@/components/DefectReasonSelect";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { sewingBandText, type BandJob } from "@/lib/sewingBandText";

export default function BandOutput({ job, onClose, onSaved }: { job: BandJob | null; onClose: () => void; onSaved: () => void }) {
  return job ? <OutputForm key={job.id} job={job} onClose={onClose} onSaved={onSaved} /> : null;
}

function OutputForm({ job, onClose, onSaved }: { job: BandJob; onClose: () => void; onSaved: () => void }) {
  const { lang } = useT(); const text = sewingBandText(lang);
  const [passed, setPassed] = useState(""); const [failed, setFailed] = useState("0");
  const [reason, setReason] = useState(""); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); const busyRef = useRef(false);
  const pending = useRef(new Map<string, string>());
  return <Modal open title={`${job.order_no} · ${text.final}`} onClose={() => { if (!busyRef.current) onClose(); }}>
    <form className="space-y-4" onSubmit={async e => {
      e.preventDefault(); if (busyRef.current) return;
      busyRef.current = true; setBusy(true); setError("");
      const body = { work_order_id: job.work_order_id, production_batch_id: job.production_batch_id, sewing_assignment_id: job.id, input_qty: 0, sewn_qty: Number(passed) + Number(failed), passed_qty: Number(passed), failed_qty: Number(failed), defect_reason: reason || null };
      const fingerprint = JSON.stringify(body); const key = pending.current.get(fingerprint) || crypto.randomUUID();
      pending.current.set(fingerprint, key);
      try {
        await api.postWithHeaders(`/api/sewing-bands/${job.id}/output`, body, { "Idempotency-Key": key });
        pending.current.delete(fingerprint); onSaved(); onClose();
      } catch (err) { setError(String(err)); }
      finally { busyRef.current = false; setBusy(false); }
    }}>
      <p className="text-sm text-[#56503f]">{text.finalHint}</p>
      <p className="text-sm tabular-nums">{text.discrepancy}: {job.reported_qty} / {job.actual_qty}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="label">{text.passed}<input className="input mt-1" type="number" min="0" step="1" required value={passed} onChange={e => setPassed(e.target.value)} /></label>
        <label className="label">{text.failed}<input className="input mt-1" type="number" min="0" step="1" required value={failed} onChange={e => setFailed(e.target.value)} /></label>
      </div>
      {Number(failed) > 0 && <label className="label" htmlFor="band-output-reason">{text.reason}<DefectReasonSelect id="band-output-reason" value={reason} onChange={setReason} required /></label>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2"><button type="button" className="btn" disabled={busy} onClick={onClose}>{text.cancel}</button><button className="btn btn-primary" disabled={busy}>{text.finalSave}</button></div>
    </form>
  </Modal>;
}
