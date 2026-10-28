"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { shipmentTransportText } from "@/lib/shipmentTransportText";

export type TransportDetails = {
  driver_name?: string | null;
  vehicle_info?: string | null;
  cargo_name?: string | null;
  driver_phone?: string | null;
};
const fields = ["driver_name", "vehicle_info", "cargo_name", "driver_phone"] as const;

export function normalizeTransportDetails(value: TransportDetails): TransportDetails | null {
  const normalized = Object.fromEntries(fields.map(key => [key, value[key]?.trim() || null]));
  return fields.some(key => normalized[key] !== null) ? normalized : null;
}

export function ShipmentTransportFields({ value, onChange, disabled = false }: {
  value: TransportDetails; onChange: (value: TransportDetails) => void; disabled?: boolean;
}) {
  const { lang } = useT();
  const text = shipmentTransportText[lang];
  return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
    {fields.map(key => <label key={key} className="block min-w-0 text-sm">
      {text[key]}
      <input className="input mt-1 block w-full" type={key === "driver_phone" ? "tel" : "text"}
        maxLength={key === "driver_phone" ? 50 : 200} value={value[key] || ""} disabled={disabled}
        onChange={event => onChange({ ...value, [key]: event.target.value })} />
    </label>)}
  </div>;
}

export default function ShipmentTransportDetails({ shipment, onChanged }: {
  shipment: { id: number; status: string; transport_details?: TransportDetails | null };
  onChanged: () => Promise<unknown>;
}) {
  const { lang } = useT();
  const text = shipmentTransportText[lang];
  const { me } = useMe();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<TransportDetails>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const allowed = ["draft", "created"].includes(shipment.status) && can(me, "storage.shipment");
  const saved = shipment.transport_details || {};
  if (!allowed && !fields.some(key => saved[key])) return null;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!allowed || busy) return;
    setBusy(true); setError("");
    try {
      await api.patch(`/api/shipments/${shipment.id}`, { transport_details: normalizeTransportDetails(draft) });
      await onChanged();
      setEditing(false);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }

  return <details className="py-2">
    <summary className="cursor-pointer text-sm font-medium">{text.title}</summary>
    <div className="mt-3 space-y-3">
      {editing && allowed ? <form onSubmit={save} className="space-y-3">
        <ShipmentTransportFields value={draft} onChange={setDraft} disabled={busy} />
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-primary" disabled={busy}>{busy ? text.saving : text.save}</button>
          <button type="button" className="btn" disabled={busy} onClick={() => setEditing(false)}>{text.cancel}</button>
        </div>
      </form> : <>
        <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          {fields.map(key => <div key={key} className="min-w-0"><dt className="text-[#6f6a5b]">{text[key]}</dt><dd className="break-words">{saved[key] || text.empty}</dd></div>)}
        </dl>
        {allowed && <button type="button" className="btn" onClick={() => { setDraft({ ...saved }); setError(""); setEditing(true); }}>{text.edit}</button>}
      </>}
    </div>
  </details>;
}
