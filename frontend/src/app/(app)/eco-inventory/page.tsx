"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import SearchableSelect from "@/components/SearchableSelect";
import { api, fetcher } from "@/lib/api";
import { ApiError } from "@/lib/errorMessages";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { ecoInventoryText, loadEcoPendingAttempt, saveEcoPendingAttempt, type EcoBatch, type EcoMaterialItem, type EcoMaterialKind, type EcoMovement } from "@/lib/ecoInventory";

type ReceiveBody = { request_key: string; item_id: number; kind: EcoMaterialKind; batch_no: string; color: string | null; quantity: string; notes: string | null };
type ConsumeBody = { request_key: string; batch_id: number; quantity: string; production_order_id: number | null; notes: string | null };
type Attempt = { endpoint: string; body: ReceiveBody | ConsumeBody };
const pageSize = 100;

export default function EcoInventoryPage() {
  const { me } = useMe(); const { lang } = useT(); const text = ecoInventoryText(lang);
  const router = useRouter(); const searchParams = useSearchParams();
  const allowed = me?.factory_code === "ECO" && can(me, "eco_inventory.read");
  const kind: EcoMaterialKind = searchParams.get("kind") === "accessory" ? "accessory" : "fabric";
  const [view, setView] = useState<"stock" | "history">("stock");
  const [page, setPage] = useState(0); const [search, setSearch] = useState("");
  const [form, setForm] = useState<"receive" | EcoBatch | null>(null);
  const [itemId, setItemId] = useState<number | null>(null); const [batchNo, setBatchNo] = useState("");
  const [color, setColor] = useState(""); const [quantity, setQuantity] = useState("");
  const [orderId, setOrderId] = useState<number | null>(null); const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false); const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(""); const [message, setMessage] = useState(""); const pending = useRef<Attempt | null>(null);
  const inFlight = useRef(false);
  const storageKey = me ? `milana:eco-inventory:pending:${me.id}:${me.factory_code}` : null;
  useEffect(() => {
    if (!storageKey) return;
    const saved = loadEcoPendingAttempt<Attempt>(storageKey);
    if (saved && (saved.endpoint === "/api/eco-inventory/receive" || saved.endpoint === "/api/eco-inventory/consume") && saved.body?.request_key) {
      pending.current = saved; setUncertain(true);
    }
  }, [storageKey]);
  const { data: rows, error: stockError, isLoading, mutate: refreshStock } = useSWR<EcoBatch[]>(allowed ? `/api/eco-inventory/stock?kind=${kind}&limit=${pageSize}&offset=${page * pageSize}` : null, fetcher);
  const { data: history, error: historyError, isLoading: historyLoading, mutate: refreshHistory } = useSWR<EcoMovement[]>(allowed && view === "history" ? `/api/eco-inventory/history?kind=${kind}&limit=${pageSize}&offset=${page * pageSize}` : null, fetcher);
  const { data: items } = useSWR<EcoMaterialItem[]>(allowed && form === "receive" ? `/api/eco-inventory/items?kind=${kind}` : null, fetcher);
  const { data: orders } = useSWR<{id: number; order_no: string}[]>(allowed && form && form !== "receive" ? "/api/eco-inventory/orders" : null, fetcher);
  const shownRows = useMemo(() => (rows || []).filter(row => `${row.item_name} ${row.sku} ${row.batch_no} ${row.color || ""}`.toLowerCase().includes(search.toLowerCase())), [rows, search]);
  function openForm(value: typeof form) {
    setForm(value); setItemId(null); setBatchNo(""); setColor(""); setQuantity(""); setNotes(""); setOrderId(null); setError(""); setMessage("");
  }
  function changeKind(value: EcoMaterialKind) { router.replace(`/eco-inventory?kind=${value}`); setPage(0); setSearch(""); openForm(null); }
  async function submit() {
    if (busy || inFlight.current || (!form && !pending.current)) return;
    if (!pending.current) {
      if (!form) return;
      if (Number(quantity) <= 0 || !Number.isFinite(Number(quantity)) || (form !== "receive" && Number(quantity) > Number(form.available_quantity))) { setError(text.validQuantity); return; }
      if (form === "receive") {
        if (!itemId || !batchNo.trim()) return;
        pending.current = { endpoint: "/api/eco-inventory/receive", body: { request_key: crypto.randomUUID(), item_id: itemId, kind, batch_no: batchNo.trim(), color: color.trim() || null, quantity, notes: notes.trim() || null } };
      } else pending.current = { endpoint: "/api/eco-inventory/consume", body: { request_key: crypto.randomUUID(), batch_id: form.id, quantity, production_order_id: orderId, notes: notes.trim() || null } };
    }
    saveEcoPendingAttempt(storageKey, pending.current);
    inFlight.current = true;
    setBusy(true); setError("");
    try {
      await api.post(pending.current.endpoint, pending.current.body);
      pending.current = null; saveEcoPendingAttempt(storageKey, null); setUncertain(false); openForm(null); setMessage(text.saved);
      await Promise.all([refreshStock(), refreshHistory()]);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : text.error);
      if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500) { pending.current = null; saveEcoPendingAttempt(storageKey, null); setUncertain(false); }
      else setUncertain(true);
    } finally { inFlight.current = false; setBusy(false); }
  }
  if (!me) return <p>{text.loading}</p>;
  if (!allowed) return <p role="alert">{text.denied}</p>;
  const activeRows = view === "stock" ? rows : history;
  const formatDate = (value: string) => new Date(value).toLocaleString(lang === "ru" ? "ru-RU" : lang === "uz" ? "uz-UZ" : "en-GB", { timeZone: "Asia/Tashkent" });
  return <div className="space-y-5">
    <PageHeader title={text.title} />
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex gap-2">{(["fabric", "accessory"] as const).map(value => <button key={value} className={`btn ${kind === value ? "btn-primary" : ""}`} disabled={busy || uncertain} onClick={() => changeKind(value)}>{text[value]}</button>)}</div>
      <div className="flex flex-wrap gap-2"><Link className="btn" href="/factory-fabric-transfers">{text.incoming}</Link>{can(me, "eco_accessories.read") && <Link className="btn" href="/eco-accessories">{text.plans}</Link>}
        {can(me, "eco_inventory.receive") && <button className="btn btn-primary" disabled={busy || uncertain} onClick={() => openForm("receive")}>{text.receive}</button>}</div>
    </div>
    {kind === "accessory" && <p className="text-sm text-[var(--erp-muted)]">{text.accessoryHelp}</p>}
    {form && <section className="card p-4 space-y-4">
      <h2 className="font-semibold">{form === "receive" ? text.receive : `${text.consume} · ${form.item_name} · ${form.batch_no}`}</h2>
      <p className="text-sm text-[var(--erp-muted)]">{form === "receive" ? text.receiveHint : text.consumeHint}</p>
      <form onSubmit={event => { event.preventDefault(); void submit(); }}>
        <fieldset disabled={busy || uncertain} className="grid gap-4 md:grid-cols-3">
          {form === "receive" && <><div><label className="label" htmlFor="eco-item">{text.item}</label><SearchableSelect<number> inputId="eco-item" value={itemId} options={(items || []).map(item => ({value: item.id, label: `${item.name} · ${item.sku} · ${item.unit}`}))} onChange={setItemId} placeholder={text.select} noResultsText={text.empty} required /></div>
            <label className="label">{text.batch}<input className="input" required maxLength={64} value={batchNo} onChange={event => setBatchNo(event.target.value)} /></label>
            <label className="label">{text.color}<input className="input" maxLength={64} value={color} onChange={event => setColor(event.target.value)} /></label></>}
          <label className="label">{text.quantity}{form !== "receive" ? ` · ${form.unit} (${text.available}: ${form.available_quantity})` : ""}<input className="input" required type="number" min="0.0001" step="0.0001" max={form === "receive" ? "9999999999.9999" : form.available_quantity} value={quantity} onChange={event => setQuantity(event.target.value)} /></label>
          {form !== "receive" && <div><label className="label" htmlFor="eco-order">{text.productionOrder}</label><SearchableSelect inputId="eco-order" value={orderId ?? 0} options={[{value: 0, label: text.none}, ...(orders || []).map(order => ({value: order.id, label: order.order_no}))]} onChange={value => setOrderId(value || null)} placeholder={text.none} noResultsText={text.empty} /></div>}
          <label className="label">{text.notes}<input className="input" maxLength={2000} value={notes} onChange={event => setNotes(event.target.value)} /></label>
        </fieldset>
        <div className="mt-4 flex flex-wrap gap-2"><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? text.loading : uncertain ? text.retry : text.save}</button><button className="btn" type="button" disabled={busy || uncertain} onClick={() => openForm(null)}>{text.cancel}</button></div>
      </form>
    </section>}
    {uncertain && <div role="status" className="space-y-2"><p>{text.retryHint}</p><button className="btn btn-primary" disabled={busy} onClick={() => void submit()}>{text.retry}</button></div>}
    {error && <p role="alert" className="text-red-700">{error}</p>}{message && <p role="status">{message}</p>}
    <section className="card p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2">{(["stock", "history"] as const).map(value => <button key={value} className={`btn ${view === value ? "btn-primary" : ""}`} onClick={() => { setView(value); setPage(0); }}>{text[value]}</button>)}</div>
        {view === "stock" && <input className="input max-w-sm" aria-label={text.search} placeholder={text.search} value={search} onChange={event => setSearch(event.target.value)} />}</div>
      {(stockError || historyError) && <p role="alert">{text.error}</p>}
      {(view === "stock" ? isLoading : historyLoading) ? <p>{text.loading}</p> : <div className="overflow-x-auto"><table className="table w-full"><thead><tr>{(view === "stock" ? [text.item, text.batch, text.color, text.balance, text.reserved, text.available, text.actions] : [text.date, text.item, text.batch, text.status, text.quantity, text.productionOrder, text.operator, text.notes]).map((label, index) => <th key={index}>{label}</th>)}</tr></thead>
        <tbody>{view === "stock" ? shownRows.map(row => <tr key={row.id}><td>{row.item_name}<div className="text-xs text-[var(--erp-muted)]">{row.sku}</div></td><td>{row.batch_no}</td><td>{row.color || "—"}</td><td>{Number(row.quantity).toLocaleString()} {row.unit}</td><td>{Number(row.reserved_quantity).toLocaleString()} {row.unit}</td><td>{Number(row.available_quantity).toLocaleString()} {row.unit}</td><td>{row.kind === "fabric" && can(me, "eco_inventory.consume") && <button className="btn" disabled={busy || uncertain || Number(row.available_quantity) <= 0} onClick={() => openForm(row)}>{text.consume}</button>}</td></tr>) : (history || []).map(row => <tr key={row.id}><td className="whitespace-nowrap">{formatDate(row.created_at)}</td><td>{row.item_name}</td><td>{row.batch_no}</td><td>{row.kind === "receive" || row.kind === "transfer_receipt" ? text.received : text.consume}</td><td>{row.kind === "consume" || row.kind === "issue" ? "−" : "+"}{Number(row.quantity).toLocaleString()} {row.unit}</td><td>{row.order_no || "—"}</td><td>{row.operator_name}</td><td>{row.notes || "—"}</td></tr>)}</tbody></table>
        {(view === "stock" ? shownRows : history || []).length === 0 && <p className="py-4">{text.empty}</p>}</div>}
      <div className="flex justify-end gap-2"><button className="btn" disabled={page === 0} onClick={() => setPage(value => value - 1)}>{text.previous}</button><button className="btn" disabled={(activeRows?.length || 0) < pageSize} onClick={() => setPage(value => value + 1)}>{text.next}</button></div>
    </section>
  </div>;
}
