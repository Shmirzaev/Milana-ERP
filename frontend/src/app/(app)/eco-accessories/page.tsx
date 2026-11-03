"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import SearchableSelect from "@/components/SearchableSelect";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { ecoAccessoriesText } from "@/lib/ecoAccessoriesText";
import { ApiError } from "@/lib/errorMessages";

type Allocation = { id: number; batch_id: number; batch_no: string; quantity: number | string; issued_quantity: number | string };
type Requirement = { item_id: number; sku: string; item_name: string; unit: string; quantity: number | string; allocations: Allocation[] };
type Plan = { id: number | null; production_order_id: number; production_no: string; bso_no: string; model_code: string;
  planned_quantity: number; status: "draft" | "pending" | "approved" | "issued"; revision: number; notes: string;
  approval_notes: string | null; sewing_started: boolean; lines: Requirement[] };
type Item = { id: number; sku: string; name: string; unit: string };
type DraftLine = { item_id: string; quantity: string };
type IssueAttempt = { orderId: number; key: string; body: { revision: number; lines: { allocation_id: number; quantity: string }[] } };

export default function EcoAccessoriesPage() {
  const { me } = useMe();
  const { lang } = useT();
  const c = ecoAccessoriesText[lang];
  const permitted = me?.factory_code === "ECO" && can(me, "eco_accessories.read", "eco_accessories.manage", "eco_accessories.approve", "eco_accessories.issue");
  const [q, setQ] = useState(""); const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<DraftLine[]>([]); const [notes, setNotes] = useState("");
  const [editingRevision, setEditingRevision] = useState<number | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [message, setMessage] = useState("");
  const issueAttempt = useRef<IssueAttempt | null>(null); const [issuePending, setIssuePending] = useState(false);
  const storageKey = me ? `eco-accessory-issue:${me.id}:${me.factory_code}` : null;
  useEffect(() => {
    if (!storageKey || !permitted) return;
    try {
      const saved: IssueAttempt | null = JSON.parse(sessionStorage.getItem(storageKey) || "null");
      if (saved && Number.isSafeInteger(saved.orderId) && saved.key && saved.body?.lines?.length) {
        issueAttempt.current = saved; setIssuePending(true); setSelectedId(saved.orderId);
      }
    } catch { /* A malformed local recovery record never grants stock access. */ }
  }, [storageKey, permitted]);
  const { data, error: listError, isLoading, mutate } = useSWR<{items: Plan[]; total: number}>(permitted ? `/api/eco-accessories?page=${page}&q=${encodeURIComponent(q)}` : null, fetcher);
  const { data: detail, error: detailError, mutate: reloadDetail } = useSWR<Plan>(permitted && selectedId ? `/api/eco-accessories/${selectedId}` : null, fetcher);
  const { data: items } = useSWR<Item[]>(permitted ? "/api/eco-accessories/items/options" : null, fetcher);
  const plan = detail;
  const editable = Boolean(plan && !plan.sewing_started && plan.status === "draft" && can(me, "eco_accessories.manage"));
  const dirty = Boolean(plan && (editingRevision !== plan.revision || JSON.stringify(draft) !== JSON.stringify(plan.lines.map(l => ({item_id: String(l.item_id), quantity: String(l.quantity)})))));
  function fail(err: unknown) {
    const key = String(err instanceof ApiError ? err.rawDetail : err instanceof Error ? err.message : "").match(/ecoAccessories\.(\w+)/)?.[1];
    setError(key && key in c.errors ? c.errors[key as keyof typeof c.errors] : c.failed);
  }
  async function selectOrder(row: Plan) {
    if (busy || issuePending) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const fresh = await api.get<Plan>(`/api/eco-accessories/${row.production_order_id}`);
      setSelectedId(fresh.production_order_id); await reloadDetail(fresh, false);
      setDraft(fresh.lines.map(line => ({item_id: String(line.item_id), quantity: String(line.quantity)})));
      setEditingRevision(fresh.revision); setNotes(fresh.notes);
    } catch (err) { fail(err); }
    finally { setBusy(false); }
  }
  async function action(actionName: "save" | "submit" | "approve" | "reopen") {
    if (!plan || busy || issuePending) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = actionName === "save" ? await api.put<Plan>(`/api/eco-accessories/${plan.production_order_id}`, {
        revision: editingRevision, notes, lines: draft.map(line => ({item_id: Number(line.item_id), quantity: line.quantity})),
      }) : await api.post<Plan>(`/api/eco-accessories/${plan.production_order_id}/${actionName}`, {revision: plan.revision, notes});
      await reloadDetail(result, false); await mutate(); setEditingRevision(result.revision);
      setDraft(result.lines.map(line => ({item_id: String(line.item_id), quantity: String(line.quantity)}))); setMessage(c.saved);
    } catch (err) { fail(err); await reloadDetail(); }
    finally { setBusy(false); }
  }
  async function issue() {
    if (!plan || busy) return;
    issueAttempt.current ||= {orderId: plan.production_order_id, key: crypto.randomUUID(), body: {revision: plan.revision,
      lines: plan.lines.flatMap(line => line.allocations.filter(a => Number(a.quantity) > Number(a.issued_quantity)).map(a => ({
        allocation_id: a.id, quantity: (Number(a.quantity) - Number(a.issued_quantity)).toFixed(4),
      })))}};
    if (storageKey) sessionStorage.setItem(storageKey, JSON.stringify(issueAttempt.current));
    setIssuePending(true); setBusy(true); setError("");
    try {
      const attempt = issueAttempt.current;
      const result = await api.postWithHeaders<Plan>(`/api/eco-accessories/${attempt.orderId}/issue`, attempt.body, {"Idempotency-Key": attempt.key});
      issueAttempt.current = null; setIssuePending(false); if (storageKey) sessionStorage.removeItem(storageKey);
      await reloadDetail(result, false); await mutate(); setMessage(c.saved);
    } catch (err) {
      fail(err);
      if (err instanceof ApiError && err.status >= 400 && err.status < 500 && err.status !== 408 && err.status !== 429) {
        issueAttempt.current = null; setIssuePending(false); if (storageKey) sessionStorage.removeItem(storageKey);
        await reloadDetail();
      }
    }
    finally { setBusy(false); }
  }
  if (!me) return <p>{c.loading}</p>;
  if (!permitted) return <p role="alert">{c.denied}</p>;
  return <div className="space-y-4">
    <PageHeader title={c.title} subtitle={c.hint}/>
    <div className="flex items-center gap-3"><label className="flex-1"><span className="sr-only">{c.search}</span><input className="input" placeholder={c.search} value={q} onChange={e => {setQ(e.target.value); setPage(1);}}/></label></div>
    {(error || listError || detailError) && <p role="alert" className="text-red-700">{error || c.failed}</p>}
    {message && <p role="status">{message}</p>}
    <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
      <section className="card p-4"><h2 className="mb-3 font-semibold">{c.orders}</h2>
        {isLoading && <p>{c.loading}</p>}{data?.items.length === 0 && <p>{c.noOrders}</p>}
        <div className="divide-y">{data?.items.map(row => <button key={row.production_order_id} type="button" disabled={busy || issuePending} onClick={() => selectOrder(row)} className={`block w-full p-3 text-left ${selectedId === row.production_order_id ? "bg-[var(--erp-bg)]" : ""}`}>
          <div className="font-semibold">{row.production_no}</div><div>{row.bso_no} · {row.model_code}</div><div className="text-sm">{c[row.status]}</div>
        </button>)}</div>
        <div className="mt-3 flex justify-between gap-2"><button className="btn" disabled={page === 1} onClick={() => setPage(page - 1)}>{c.previous}</button><span>{page}</span><button className="btn" disabled={page * 30 >= (data?.total || 0)} onClick={() => setPage(page + 1)}>{c.next}</button></div>
      </section>
      <section className="card p-4 space-y-4">{!plan ? <p>{c.select}</p> : <>
        <h2 className="font-semibold">{plan.production_no} · {plan.bso_no}</h2>
        <p>{c.model}: {plan.model_code} · {c.quantity}: {plan.planned_quantity} · {c[plan.status]}</p>
        {plan.sewing_started && <p>{c.started}</p>}
        {editable ? <fieldset disabled={busy || issuePending} className="space-y-3">
          {draft.map((line, index) => <div className="flex flex-wrap items-end gap-2" key={index}>
            <label className="min-w-48 flex-1"><span className="label">{c.accessory}</span><SearchableSelect value={line.item_id} placeholder={c.accessory} noResultsText={c.noAccessories} options={(items || []).map(item => ({value: String(item.id), label: `${item.sku} · ${item.name} (${item.unit})`}))} onChange={value => setDraft(rows => rows.map((r, i) => i === index ? {...r, item_id: value} : r))}/></label>
            <label><span className="label">{c.required}</span><input className="input w-36" type="number" min="0.0001" step="0.0001" value={line.quantity} onChange={e => setDraft(rows => rows.map((r, i) => i === index ? {...r, quantity: e.target.value} : r))}/></label>
            <button className="btn" onClick={() => setDraft(rows => rows.filter((_, i) => i !== index))}>{c.remove}</button>
          </div>)}
          {!draft.length && <p>{c.noAccessories}</p>}<button className="btn" onClick={() => setDraft(rows => [...rows, {item_id: "", quantity: ""}])}>{c.add}</button>
        </fieldset> : <div className="overflow-x-auto"><table className="table w-full"><thead><tr><th>{c.accessory}</th><th>{c.required}</th><th>{c.allocated}</th><th>{c.issuedQty}</th></tr></thead><tbody>
          {plan.lines.map(line => <tr key={line.item_id}><td>{line.sku} · {line.item_name}</td><td>{line.quantity} {line.unit}</td><td>{line.allocations.map(a => `${a.batch_no}: ${a.quantity}`).join(", ") || "—"}</td><td>{line.allocations.reduce((sum, a) => sum + Number(a.issued_quantity), 0)} {line.unit}</td></tr>)}
        </tbody></table></div>}
        <label className="block"><span className="label">{c.notes}</span><textarea className="input" value={notes} onChange={e => setNotes(e.target.value)} disabled={busy || issuePending}/></label>
        {plan.approval_notes && <p>{plan.approval_notes}</p>}
        <div className="flex flex-wrap gap-2">
          {editable && <button className="btn" disabled={busy || issuePending} onClick={() => action("save")}>{c.save}</button>}
          {editable && plan.id && <button className="btn btn-primary" disabled={busy || issuePending || dirty} onClick={() => action("submit")}>{c.submit}</button>}
          {!plan.sewing_started && plan.status === "pending" && can(me, "eco_accessories.approve") && <button className="btn btn-primary" disabled={busy || issuePending} onClick={() => action("approve")}>{c.approve}</button>}
          {!plan.sewing_started && ["pending", "approved"].includes(plan.status) && can(me, "eco_accessories.approve") && <button className="btn" disabled={busy || issuePending} onClick={() => action("reopen")}>{c.reopen}</button>}
          {(plan.status === "approved" && plan.lines.some(l => l.allocations.some(a => Number(a.quantity) > Number(a.issued_quantity))) || issuePending) && can(me, "eco_accessories.issue") && <button className="btn btn-primary" disabled={busy} onClick={() => issue()}>{issuePending ? c.retry : c.issue}</button>}
        </div>
      </>}</section>
    </div>
  </div>;
}
