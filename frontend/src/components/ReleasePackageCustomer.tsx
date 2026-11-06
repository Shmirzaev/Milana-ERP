"use client";
import { useRef, useState } from "react";
import useSWR, { mutate } from "swr";
import Modal from "@/components/Modal";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { packageCustomerText } from "@/lib/packageCustomerText";

type Pack = { id: number; package_no: string; status?: string };
type CustomerAccess = {
  customer_names: string[];
  released_for_any_customer: boolean;
  released_at?: string | null;
  released_by_name?: string | null;
  release_reason?: string | null;
};

export default function ReleasePackageCustomer({ packages, showAccess = false }: { packages: Pack[]; showAccess?: boolean }) {
  const { me } = useMe();
  const { lang } = useT();
  const copy = packageCustomerText[lang];
  const { data: access, error: accessError } = useSWR<CustomerAccess>(
    showAccess && packages.length === 1 ? `/api/packages/${packages[0]!.id}/customer-access` : null, fetcher,
  );
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const pendingRequest = useRef<{ payload: string; key: string } | null>(null);
  const allowed = can(me, "*") || (me?.role?.toLowerCase() === "admin" && !me.access_configured);
  const eligible = packages.filter(pack => !pack.status || pack.status === "received_in_storage");

  return <div className="space-y-2 text-sm">
    {showAccess && accessError && <p role="alert" className="text-red-700">{copy.accessFailed}</p>}
    {showAccess && access && <div>
      <p>{access.released_for_any_customer || !access.customer_names.length
        ? copy.unrestricted : `${copy.assigned}: ${access.customer_names.join(", ")}`}</p>
      {access.released_for_any_customer && <p className="text-slate-500">
        {copy.releasedBy}: {access.released_by_name || "—"}
        {access.released_at && ` · ${new Date(access.released_at).toLocaleString(lang === "uz" ? "uz-UZ" : lang === "ru" ? "ru-RU" : "en-GB", { timeZone: "Asia/Tashkent" })}`}
        {access.release_reason && ` · ${access.release_reason}`}
      </p>}
    </div>}
    {allowed && eligible.length > 0 && !access?.released_for_any_customer && (!showAccess || !!access?.customer_names.length) && <button type="button" className="btn" onClick={() => {
      pendingRequest.current = null;
      setSelected(eligible.slice(0, 200).map(pack => pack.id)); setReason(""); setError(""); setMessage(""); setOpen(true);
    }}>{copy.release}</button>}
    {message && <p role="status">{message}</p>}
    <Modal open={open && allowed} title={copy.release} onClose={() => { if (!busy) setOpen(false); }} closeOnOutsideClick={!busy}>
      <form className="space-y-4" onSubmit={async event => {
        event.preventDefault();
        if (busy || !selected.length || !reason.trim()) return;
        setBusy(true); setError(""); setMessage("");
        try {
          const payload = { package_ids: [...selected].sort((a, b) => a - b), reason: reason.trim() };
          const serialized = JSON.stringify(payload);
          if (pendingRequest.current?.payload !== serialized) pendingRequest.current = { payload: serialized, key: crypto.randomUUID() };
          await api.postWithHeaders("/api/packages/customer-release", payload, { "Idempotency-Key": pendingRequest.current.key });
          setOpen(false); setMessage(copy.success);
          void mutate(key => typeof key === "string" && ["/api/packages", "/api/sales-orders/ready-stock-options", "/api/warehouse-reservations", "/api/shipments"].some(prefix => key.startsWith(prefix)));
        } catch (caught) { setError(caught instanceof Error ? caught.message : copy.failed); }
        finally { setBusy(false); }
      }}>
        <p>{copy.explanation}</p>
        <fieldset disabled={busy} className="space-y-2">
          <legend className="mb-2 font-medium">{copy.select}</legend>
          <div className="max-h-56 space-y-2 overflow-auto">
            {packages.map(pack => <label key={pack.id} className="flex items-center gap-2">
              <input type="checkbox" disabled={!!pack.status && pack.status !== "received_in_storage"} checked={selected.includes(pack.id)} onChange={event => {
                if (event.target.checked && selected.length >= 200) { setError(copy.tooMany); return; }
                setError(""); setSelected(values => event.target.checked ? [...values, pack.id] : values.filter(id => id !== pack.id));
              }} />{pack.package_no}
            </label>)}
          </div>
          <label className="block"><span className="label">{copy.reason}</span>
            <textarea className="input" value={reason} onChange={event => setReason(event.target.value)} required maxLength={1000} rows={3} />
          </label>
        </fieldset>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" className="btn" disabled={busy} onClick={() => setOpen(false)}>{copy.cancel}</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !selected.length || !reason.trim()}>{busy ? copy.saving : copy.release}</button>
        </div>
      </form>
    </Modal>
  </div>;
}
