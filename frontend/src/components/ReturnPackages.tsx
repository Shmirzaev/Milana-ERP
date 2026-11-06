"use client";
import { useState } from "react";
import Modal from "@/components/Modal";
import { api } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { packageReturnText } from "@/lib/packageReturnText";

export default function ReturnPackages({ packages, onReturned }: {
  packages: { id: number; package_no: string }[]; onReturned: () => void;
}) {
  const { me } = useMe(); const { lang } = useT(); const c = packageReturnText[lang];
  const [open, setOpen] = useState(false); const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  if (!can(me, "storage.packages")) return null;
  return <><button className="btn" type="button" onClick={() => { setOpen(true); setError(""); }}>{c.return}</button>
    <Modal open={open} onClose={() => { if (!busy) setOpen(false); }} title={c.return}>
      <form className="space-y-4" onSubmit={async event => {
        event.preventDefault(); if (busy) return; setBusy(true); setError("");
        try { await api.post("/api/packages/return-to-packaging", { package_ids: packages.map(p => p.id), reason }); setOpen(false); onReturned(); }
        catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
        finally { setBusy(false); }
      }}>
        <p>{c.confirm}</p><p className="text-sm">{packages.map(p => p.package_no).join(", ")}</p>
        <label className="label">{c.reason}<textarea className="input" required minLength={3} maxLength={1000} value={reason} disabled={busy} onChange={e => setReason(e.target.value)} /></label>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2"><button type="button" className="btn" disabled={busy} onClick={() => setOpen(false)}>{c.cancel}</button><button className="btn btn-primary" disabled={busy || reason.trim().length < 3}>{c.return}</button></div>
      </form>
    </Modal></>;
}
