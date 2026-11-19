"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import SearchableSelect from "@/components/SearchableSelect";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher, fetchResponse } from "@/lib/api";
import { ApiError } from "@/lib/errorMessages";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { ecoInventoryText, fabricTransferOutstanding, loadEcoPendingAttempt, retainEcoPendingAfterFailure, saveEcoPendingAttempt, transferStatusText, type FabricSourceBatch, type FabricTransfer, type FabricTransferStatus } from "@/lib/ecoInventory";

type DraftRow = FabricSourceBatch & { sendQuantity: string };
type Attempt = { endpoint: string; body: { request_key: string; notes: string | null; lines: ({ source_batch_id: number; quantity: string } | { line_id: number; quantity: string })[] } };
const pageSize = 50;

export default function FactoryFabricTransfersPage() {
  const { me } = useMe(); const { lang } = useT(); const text = ecoInventoryText(lang); const dialogs = useDialogs();
  const allowed = !!me && (me.factory_code === "MIL" || me.factory_code === "ECO") && can(me, "factory_fabric_transfers.read");
  const canDispatch = allowed && me?.factory_code === "MIL" && can(me, "factory_fabric_transfers.dispatch");
  const canReceive = allowed && me?.factory_code === "ECO" && can(me, "factory_fabric_transfers.receive");
  const [status, setStatus] = useState<FabricTransferStatus | "">(""); const [page, setPage] = useState(0);
  const [sourceId, setSourceId] = useState<number | null>(null); const [sourceQuery, setSourceQuery] = useState("");
  const [draft, setDraft] = useState<DraftRow[]>([]); const [notes, setNotes] = useState("");
  const [receiving, setReceiving] = useState<FabricTransfer | null>(null); const [receiptQuantities, setReceiptQuantities] = useState<Record<number, string>>({});
  const [receiptNotes, setReceiptNotes] = useState(""); const [busy, setBusy] = useState(false); const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(""); const [message, setMessage] = useState(""); const pending = useRef<Attempt | null>(null);
  const confirming = useRef(false); const inFlight = useRef(false);
  const storageKey = me ? `milana:factory-fabric-transfers:pending:${me.id}:${me.factory_code}` : null;
  useEffect(() => {
    if (!storageKey) return;
    const saved = loadEcoPendingAttempt<Attempt>(storageKey);
    if (saved && /^\/api\/factory-fabric-transfers\/(dispatch|\d+\/receive)$/.test(saved.endpoint) && saved.body?.request_key) {
      pending.current = saved; setUncertain(true);
    }
  }, [storageKey]);
  const { data, error: loadError, isLoading, mutate } = useSWR<FabricTransfer[]>(allowed ? `/api/factory-fabric-transfers?limit=${pageSize}&offset=${page * pageSize}${status ? `&status=${status}` : ""}` : null, fetcher);
  const { data: sources, mutate: refreshSources } = useSWR<FabricSourceBatch[]>(canDispatch ? `/api/factory-fabric-transfers/source-batches?q=${encodeURIComponent(sourceQuery)}` : null, fetcher);
  function addFabric() {
    const row = sources?.find(source => source.id === sourceId);
    if (!row || draft.some(line => line.id === row.id)) return;
    setDraft(previous => [...previous, {...row, sendQuantity: ""}]); setSourceId(null); setError("");
  }
  async function runAttempt() {
    if (!pending.current || busy || inFlight.current) return;
    inFlight.current = true;
    saveEcoPendingAttempt(storageKey, pending.current);
    setBusy(true); setError(""); setMessage("");
    try {
      await api.post(pending.current.endpoint, pending.current.body);
      const sent = pending.current.endpoint.endsWith("/dispatch");
      pending.current = null; saveEcoPendingAttempt(storageKey, null); setUncertain(false); setReceiving(null);
      if (sent) { setDraft([]); setNotes(""); }
      setMessage(text.saved); await Promise.all([mutate(), refreshSources()]);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : text.error);
      if (!retainEcoPendingAfterFailure(storageKey, failure instanceof ApiError ? failure.status : 0, uncertain)) { pending.current = null; setUncertain(false); }
      else setUncertain(true);
    } finally { inFlight.current = false; setBusy(false); }
  }
  async function send() {
    if (busy || uncertain || confirming.current || !draft.length) return;
    if (draft.some(row => !Number.isFinite(Number(row.sendQuantity)) || Number(row.sendQuantity) <= 0 || Number(row.sendQuantity) > Number(row.available_quantity))) { setError(text.validQuantity); return; }
    confirming.current = true;
    try {
      if (!await dialogs.ask({title: text.dispatch, message: text.confirmDispatch, confirmText: text.confirm})) return;
      pending.current = { endpoint: "/api/factory-fabric-transfers/dispatch", body: { request_key: crypto.randomUUID(), notes: notes.trim() || null, lines: draft.map(row => ({source_batch_id: row.id, quantity: row.sendQuantity})) } };
      await runAttempt();
    } finally { confirming.current = false; }
  }
  function openReceipt(record: FabricTransfer) {
    setReceiving(record); setReceiptNotes(""); setReceiptQuantities(Object.fromEntries(record.lines.map(row => [row.id, "0"]))); setError(""); setMessage("");
  }
  async function receive() {
    if (!receiving || busy || uncertain) return;
    const lines = receiving.lines.map(row => ({line_id: row.id, quantity: receiptQuantities[row.id] || "0"})).filter(row => Number(row.quantity) > 0);
    if (!lines.length || receiving.lines.some(row => !Number.isFinite(Number(receiptQuantities[row.id] || 0)) || Number(receiptQuantities[row.id] || 0) < 0 || Number(receiptQuantities[row.id] || 0) > fabricTransferOutstanding(row))) { setError(text.validQuantity); return; }
    pending.current = {endpoint: `/api/factory-fabric-transfers/${receiving.id}/receive`, body: {request_key: crypto.randomUUID(), notes: receiptNotes.trim() || null, lines}};
    await runAttempt();
  }
  async function download(record: FabricTransfer) {
    try {
      const response = await fetchResponse(`/api/factory-fabric-transfers/${record.id}/excel`, {credentials: "include"});
      if (!response.ok) throw new Error(text.error);
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement("a");
      link.href = url; link.download = `${record.number}.xlsx`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (failure) { setError(failure instanceof Error ? failure.message : text.error); }
  }
  if (!me) return <p>{text.loading}</p>;
  if (!allowed) return <p role="alert">{text.denied}</p>;
  const formatDate = (value: string) => new Date(value).toLocaleString(lang === "ru" ? "ru-RU" : lang === "uz" ? "uz-UZ" : "en-GB", {timeZone: "Asia/Tashkent"});
  return <div className="space-y-5">
    <PageHeader title={text.transfers} subtitle={text.transferHint} />
    {me.factory_code === "ECO" && can(me, "eco_inventory.read") && <Link className="btn" href="/eco-inventory">{text.title}</Link>}
    {canDispatch && <section className="card p-4 space-y-4">
      <h2 className="font-semibold">{text.dispatch}</h2><p className="text-sm text-[var(--erp-muted)]">{text.dispatchHint}</p>
      <fieldset disabled={busy || uncertain} className="flex flex-wrap items-end gap-3">
        <div className="min-w-64 flex-1"><label htmlFor="transfer-source" className="label">{text.item}</label><SearchableSelect<number> inputId="transfer-source" value={sourceId}
          options={(sources || []).map(row => ({value: row.id, label: `${row.item_name} · ${row.batch_no} · ${row.color || "—"} · ${text.available}: ${row.available_quantity} ${row.unit}`, disabled: draft.some(line => line.id === row.id) || Number(row.available_quantity) <= 0}))}
          onChange={setSourceId} placeholder={text.select} noResultsText={text.empty} serverFilter onSearchChange={setSourceQuery} disabled={busy || uncertain} /></div>
        <button className="btn" type="button" disabled={!sourceId} onClick={addFabric}>{text.add}</button>
      </fieldset>
      {draft.length > 0 && <form onSubmit={event => {event.preventDefault(); void send();}} className="space-y-4">
        <fieldset disabled={busy || uncertain}><div className="overflow-x-auto"><table className="table w-full"><thead><tr>{[text.item, text.batch, text.color, text.available, text.quantity, text.actions].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>
          {draft.map(row => <tr key={row.id}><td>{row.item_name}</td><td>{row.batch_no}</td><td>{row.color || "—"}</td><td>{Number(row.available_quantity).toLocaleString()} {row.unit}</td><td><label className="sr-only" htmlFor={`send-${row.id}`}>{text.quantity} {row.item_name} {row.batch_no}</label><input id={`send-${row.id}`} className="input min-w-28" required type="number" min="0.0001" step="0.0001" max={row.available_quantity} value={row.sendQuantity} onChange={event => setDraft(previous => previous.map(line => line.id === row.id ? {...line, sendQuantity: event.target.value} : line))} /></td><td><button className="btn" type="button" onClick={() => setDraft(previous => previous.filter(line => line.id !== row.id))}>{text.remove}</button></td></tr>)}</tbody></table></div>
          <label className="label mt-3">{text.notes}<input className="input" maxLength={2000} value={notes} onChange={event => setNotes(event.target.value)} /></label></fieldset>
        <button className="btn btn-primary" disabled={busy || uncertain}>{busy ? text.loading : text.dispatch}</button>
      </form>}
    </section>}
    {uncertain && <div role="status" className="space-y-2"><p>{text.retryHint}</p><button className="btn btn-primary" disabled={busy} onClick={() => void runAttempt()}>{text.retry}</button></div>}
    {error && <p role="alert" className="text-red-700">{error}</p>}{message && <p role="status">{message}</p>}
    <section className="card p-4 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3"><h2 className="font-semibold">{me.factory_code === "ECO" ? text.incoming : text.history}</h2>
        <label className="label">{text.status}<select className="input" value={status} onChange={event => {setStatus(event.target.value as FabricTransferStatus | ""); setPage(0);}}><option value="">{text.all}</option>{(["in_transit", "partially_received", "received"] as const).map(value => <option value={value} key={value}>{transferStatusText(value, text)}</option>)}</select></label></div>
      {loadError && <p role="alert">{text.error}</p>}{isLoading && <p>{text.loading}</p>}{data?.length === 0 && <p>{text.empty}</p>}
      {(data || []).map(record => <details key={record.id} className="border-t pt-3" open={receiving?.id === record.id || undefined}>
        <summary className="cursor-pointer py-2"><strong>{record.number}</strong> · {formatDate(record.dispatched_at)} · {record.operator_name} · {transferStatusText(record.status, text)}</summary>
        <div className="space-y-3 py-3"><div className="flex flex-wrap gap-2"><button className="btn" onClick={() => void download(record)}>{text.excel}</button>
          {canReceive && record.status !== "received" && receiving?.id !== record.id && <button className="btn btn-primary" disabled={busy || uncertain} onClick={() => openReceipt(record)}>{text.confirmReceive}</button>}</div>
          {record.notes && <p className="text-sm">{record.notes}</p>}
          {receiving?.id === record.id && <p className="text-sm">{text.receiptHint}</p>}
          <div className="overflow-x-auto"><table className="table w-full"><thead><tr>{[text.item, text.batch, text.color, text.sent, text.received, text.outstanding, ...(receiving?.id === record.id ? [text.receiveNow] : [])].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>
            {record.lines.map(row => <tr key={row.id}><td>{row.item_name}</td><td>{row.batch_no}</td><td>{row.color || "—"}</td><td>{Number(row.quantity).toLocaleString()} {row.unit}</td><td>{Number(row.received_quantity).toLocaleString()} {row.unit}</td><td>{fabricTransferOutstanding(row).toLocaleString()} {row.unit}</td>{receiving?.id === record.id && <td><label className="sr-only" htmlFor={`receive-${row.id}`}>{text.receiveNow} {row.item_name} {row.batch_no}</label><input id={`receive-${row.id}`} className="input min-w-28" type="number" min="0" step="0.0001" max={fabricTransferOutstanding(row)} disabled={busy || uncertain || Number(row.quantity) === Number(row.received_quantity)} value={receiptQuantities[row.id] || "0"} onChange={event => setReceiptQuantities(previous => ({...previous, [row.id]: event.target.value}))} /></td>}</tr>)}</tbody></table></div>
          {receiving?.id === record.id && <><label className="label">{text.notes}<input className="input" maxLength={2000} disabled={busy || uncertain} value={receiptNotes} onChange={event => setReceiptNotes(event.target.value)} /></label><div className="flex gap-2"><button className="btn btn-primary" disabled={busy || uncertain} onClick={() => void receive()}>{busy ? text.loading : text.confirmReceive}</button><button className="btn" disabled={busy || uncertain} onClick={() => setReceiving(null)}>{text.cancel}</button></div></>}
        </div>
      </details>)}
      <div className="flex justify-end gap-2"><button className="btn" disabled={page === 0} onClick={() => setPage(value => value - 1)}>{text.previous}</button><button className="btn" disabled={(data?.length || 0) < pageSize} onClick={() => setPage(value => value + 1)}>{text.next}</button></div>
    </section>
  </div>;
}
