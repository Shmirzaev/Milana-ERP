"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { shipmentReviewText } from "@/lib/shipmentReviewText";
import type { ShipmentPreparation } from "@/components/ShipmentPreparationWorkspace";

export default function ShipmentReviewPanel({ preparation, onChanged }: {
  preparation: ShipmentPreparation; onChanged: () => Promise<unknown>;
}) {
  const { lang } = useT();
  const text = shipmentReviewText[lang];
  const { me } = useMe();
  const [editing, setEditing] = useState<number | "amount" | null>(null);
  const [values, setValues] = useState<Record<number, string>>({});
  const [amount, setAmount] = useState("");
  const [editBasis, setEditBasis] = useState("");
  const [expectedQuantity, setExpectedQuantity] = useState(0);
  const [confirmExtraReceipt, setConfirmExtraReceipt] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const review = preparation.review;
  const pkg = preparation.packages.find(row => row.id === editing);
  const open = ["created", "draft"].includes(preparation.shipment.status);
  const allowed = open && can(me, "storage.shipment");
  const canReceiveExtra = can(me, "storage.shipment") && can(me, "storage.packages");
  const hasIncrease = !!pkg?.quantity_items?.some(row => Number(values[row.item_id]) > row.quantity);
  if (!review) return null;

  function begin(id: number | "amount") {
    setEditing(id); setReason(""); setError(""); setAmount(review?.amount ?? "");
    setEditBasis(review?.basis || "");
    setConfirmExtraReceipt(false);
    const target = preparation.packages.find(row => row.id === id);
    setExpectedQuantity(target?.quantity || 0);
    setValues(Object.fromEntries((target?.quantity_items || []).map(row => [row.item_id, String(row.quantity)])));
  }
  async function remove() {
    if (!pkg || busy || reason.trim().length < 3) return;
    setBusy(true); setError("");
    try {
      await api.post(`/api/shipments/${preparation.shipment.id}/packages/${pkg.id}/remove`, { reason: reason.trim() });
      await onChanged(); setEditing(null);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busy || reason.trim().length < 3) return;
    setBusy(true); setError("");
    try {
      if (editing === "amount") {
        await api.post(`/api/shipments/${preparation.shipment.id}/review-amount`, { amount, reason: reason.trim(), basis: editBasis });
      } else if (pkg) {
        await api.post(`/api/shipments/${preparation.shipment.id}/packages/${pkg.id}/quantity`, {
          expected_quantity: expectedQuantity, reason: reason.trim(),
          confirm_extra_receipt: confirmExtraReceipt,
          items: (pkg.quantity_items || []).map(row => ({ item_id: row.item_id, quantity: Number(values[row.item_id]) })),
        });
      }
      await onChanged(); setEditing(null);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }
  return <div className="border-t px-4 py-3 space-y-3">
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm tabular-nums">
      <span>{text.scanned}: <strong>{review.quantity}</strong> · {review.packages_count} {text.packs}</span>
      <span>{text.calculated}: {review.calculated_amount ?? text.noPrices}</span>
      <span>{text.amount}: <strong>{review.amount ?? text.noPrices}</strong></span>
      {allowed && review.packages_count > 0 && <button type="button" className="btn" onClick={() => begin("amount")} disabled={busy}>{text.review}</button>}
    </div>
    {review.review_stale && <p role="alert" className="text-amber-800 text-sm">{text.stale}</p>}
    {allowed && preparation.packages.some(row => row.scanned) && <details><summary className="cursor-pointer text-sm">{text.edit}</summary>
      <div className="divide-y mt-2">{preparation.packages.filter(row => row.scanned).map(row => <div key={row.id} className="flex items-center justify-between gap-3 py-2 text-sm"><span>{row.package_no} · {row.quantity} {text.pieces}</span><button type="button" className="btn" disabled={busy} onClick={() => begin(row.id)}>{text.edit}</button></div>)}</div>
    </details>}
    {editing !== null && allowed && <form className="space-y-3 border-t pt-3" onSubmit={save}>
      <p className="text-sm">{editing === "amount" ? text.amountHint : text.qtyHint}</p>
      {editing === "amount" ? <label className="block text-sm">{text.amount}<input className="input block mt-1 max-w-64" inputMode="decimal" type="number" step="0.01" min="0" max="999999999999.99" required value={amount} onChange={e => setAmount(e.target.value)} disabled={busy} /></label> : <>
        <p className="font-semibold text-sm">{pkg?.package_no}</p>
        <div className="flex flex-wrap gap-3">{pkg?.quantity_items?.map(row => <label key={row.item_id} className="text-sm">{row.color} / {row.size}<input aria-label={`${text.quantity}: ${row.color} / ${row.size}`} className="input block mt-1 w-28" type="number" step="1" min="0" max={canReceiveExtra ? 10000 : row.quantity} required value={values[row.item_id] ?? ""} onChange={e => setValues(previous => ({ ...previous, [row.item_id]: e.target.value }))} disabled={busy} /></label>)}</div>
        {hasIncrease && <label className="flex items-start gap-2 text-sm"><input type="checkbox" required checked={confirmExtraReceipt} onChange={e => setConfirmExtraReceipt(e.target.checked)} disabled={busy || !canReceiveExtra} /><span>{text.extraReceipt}</span></label>}
      </>}
      <label className="block text-sm">{text.reason}<input className="input block mt-1 w-full" required minLength={3} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} disabled={busy} /></label>
      {error && <p role="alert" className="text-red-700 text-sm">{error}</p>}
      <div className="flex flex-wrap gap-2">{pkg && <button className="btn" type="button" disabled={busy || reason.trim().length < 3} onClick={() => void remove()}>{text.remove}</button>}<button className="btn btn-primary" disabled={busy || reason.trim().length < 3}>{text.save}</button><button className="btn" type="button" disabled={busy} onClick={() => setEditing(null)}>{text.cancel}</button></div>
    </form>}
  </div>;
}
