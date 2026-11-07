"use client";

import { useId, useState } from "react";
import Modal from "@/components/Modal";
import { api } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { cuttingRejectionText } from "@/lib/cuttingRejectionText";

export default function CuttingRejectOrder({ workOrderId, status, hasOutput, orderLabel, onRejected }: {
  workOrderId: number;
  status?: string | null;
  hasOutput: boolean;
  orderLabel: string;
  onRejected: () => Promise<unknown>;
}) {
  const { me } = useMe();
  const { lang } = useT();
  const text = cuttingRejectionText[lang];
  const reasonId = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [rejected, setRejected] = useState(false);
  const [error, setError] = useState("");
  if (!workOrderId || !can(me, "cutting.records", "planning.production")) return null;
  if (rejected) return <div className="text-sm text-red-700"><span role="status">{text.saved}</span>{error && <p role="alert">{error}</p>}</div>;
  if (hasOutput || ["completed", "rejected", "cancelled"].includes(status || "")) return null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!reason.trim()) { setError(text.required); return; }
    setBusy(true); setError("");
    try {
      await api.post(`/api/work-orders/${workOrderId}/reject-cutting`, { reason: reason.trim() });
      setOpen(false); setRejected(true);
      await onRejected();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally { setBusy(false); }
  }

  return <>
    <button type="button" className="btn text-red-700" onClick={() => { setReason(""); setError(""); setOpen(true); }}>{text.action}</button>
    <div className="contents whitespace-normal">
    <Modal open={open} title={text.title} onClose={() => { if (!busy) setOpen(false); }} closeOnOutsideClick={!busy}>
      <form onSubmit={submit} className="space-y-4">
        <p className="font-semibold text-sm">{orderLabel}</p>
        <p className="text-sm text-[#56503f]">{text.hint}</p>
        <label htmlFor={reasonId} className="block text-sm">{text.reason}
          <textarea id={reasonId} className="input mt-1 block" rows={3} required maxLength={2000} autoFocus
            value={reason} onChange={event => setReason(event.target.value)} disabled={busy} />
        </label>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" className="btn" disabled={busy} onClick={() => setOpen(false)}>{text.cancel}</button>
          <button type="submit" className="btn btn-danger" disabled={busy || !reason.trim()}>{text.action}</button>
        </div>
      </form>
    </Modal>
    </div>
  </>;
}
