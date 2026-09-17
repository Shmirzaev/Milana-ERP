"use client";
import { useEffect, useRef, useState } from "react";
import { Camera, Download, Trash2 } from "lucide-react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import FabricRollCamera from "@/components/FabricRollCamera";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { isFabricRollCode } from "@/lib/fabricScans";
import { useDialogs } from "@/components/DialogProvider";

type Roll = { code: string; fabric_name: string; batch_no: string; color?: string; roll_number: number;
  quantity: number; unit: string; status?: string; dispatch_id?: number; returned_at?: string; return_operator_name?: string };
type Dispatch = { id: number; number: string; sent_at: string; operator_name: string; sent_rolls: number;
  sent_kg: number; outstanding_rolls: number; outstanding_kg: number; rows: Roll[] };
type Report = { items: Dispatch[]; total: number; outstanding_rolls: number; outstanding_kg: number };
export default function EcoFabricTransfers() {
  const { me } = useMe(); const { t, lang } = useT(); const dialogs = useDialogs();
  const permitted = me?.factory_code === "MIL" && can(me, "inventory.eco_transfers");
  const [mode, setMode] = useState<"send" | "return">("send");
  const [code, setCode] = useState(""); const [draft, setDraft] = useState<Roll[]>([]);
  const [day, setDay] = useState(""); const [page, setPage] = useState(1);
  const [camera, setCamera] = useState(false); const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false); const [frozen, setFrozen] = useState(false);
  const [failure, setFailure] = useState(""); const [message, setMessage] = useState("");
  const [lastDispatch, setLastDispatch] = useState<Dispatch | null>(null);
  const input = useRef<HTMLInputElement>(null); const timer = useRef<ReturnType<typeof setTimeout>>();
  const queue = useRef(Promise.resolve()); const pending = useRef(0); const sendKey = useRef("");
  const returnAttempt = useRef<{ code: string; dispatch_id: number; request_key: string } | null>(null);
  const [returnRetry, setReturnRetry] = useState(false);
  useEffect(() => () => clearTimeout(timer.current), []);
  const { data, error, isLoading, mutate } = useSWR<Report>(permitted ? `/api/eco-fabric-transfers?page=${page}${day ? `&report_date=${day}` : ""}` : null, fetcher);
  function fail(err: unknown) {
    const raw = err instanceof Error ? err.message : "";
    const key = raw.match(/(?:ecoTransfers|fabricScans)\.\w+/)?.[0];
    setFailure(key ? t(key) : raw || t("ecoTransfers.failed"));
  }
  async function download(dispatch: Dispatch) {
    try {
      const response = await fetch(`/api/eco-fabric-transfers/${dispatch.id}/pdf?lang=${lang}`, { credentials: "include" });
      if (!response.ok) throw new Error(t("ecoTransfers.pdfFailed"));
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement("a");
      link.href = url; link.download = `${dispatch.number}.pdf`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) { fail(err); }
  }
  async function completeReturn(attempt: NonNullable<typeof returnAttempt.current>) {
    try {
      await api.post("/api/eco-fabric-transfers/return", attempt);
    } catch (err) {
      if (err instanceof Error && /^4\d\d:/.test(err.message)) {
        returnAttempt.current = null; setReturnRetry(false);
      }
      throw err;
    }
    returnAttempt.current = null; setReturnRetry(false);
    setMessage(t("ecoTransfers.returned")); await mutate();
  }
  function scan(value: string): Promise<void> {
    clearTimeout(timer.current); value = value.trim();
    if (!value || frozen || sending || returnAttempt.current) return Promise.resolve();
    const action = mode; setCode(""); pending.current++; setBusy(true);
    const task = queue.current.then(async () => {
      setFailure(""); setMessage("");
      try {
        // A failed return must be retried using its original dispatch identity.
        if (returnAttempt.current) throw new Error(t("ecoTransfers.retryFirst"));
        const row = await api.post<Roll>("/api/eco-fabric-transfers/scan", { code: value });
        if (action === "send") {
          if (row.status === "sent") throw new Error(t("ecoTransfers.alreadySent"));
          setDraft((rows) => rows.some((r) => r.code === row.code) ? rows : [...rows, row]);
          setMessage(t("ecoTransfers.added"));
        } else {
          if (row.status !== "sent" || !row.dispatch_id) throw new Error(t("ecoTransfers.notSent"));
          returnAttempt.current = { code: row.code, dispatch_id: row.dispatch_id, request_key: crypto.randomUUID() };
          setReturnRetry(true); await completeReturn(returnAttempt.current);
        }
      } catch (err) { fail(err); }
      finally { pending.current--; setBusy(pending.current > 0); requestAnimationFrame(() => input.current?.focus()); }
    }); queue.current = task; return task;
  }
  async function send() {
    if (!draft.length || busy || sending) return;
    if (!frozen && !await dialogs.ask({ title: t("ecoTransfers.markSent"), message: t("ecoTransfers.confirm"), confirmText: t("ecoTransfers.markSent") })) return;
    setFrozen(true); setSending(true); setFailure("");
    sendKey.current ||= crypto.randomUUID();
    try {
      const result = await api.post<Dispatch>("/api/eco-fabric-transfers/send", { request_key: sendKey.current, codes: draft.map((row) => row.code) });
      setLastDispatch(result); setDraft([]); setFrozen(false); sendKey.current = "";
      setMessage(t("ecoTransfers.sent")); setDay(""); setPage(1); await mutate(); await download(result);
    } catch (err) {
      fail(err);
      if (err instanceof Error && /^4\d\d:/.test(err.message)) {
        setFrozen(false); sendKey.current = "";
      }
    }
    finally { setSending(false); }
  }
  function rollTable(rows: Roll[], removable = false) {
    return <div className="overflow-x-auto"><table className="table w-full"><thead><tr>
      {["fabricScans.fabric", "fabricScans.batch", "fabricScans.color", "fabricScans.roll", "ecoTransfers.weight", ...(removable ? ["common.actions"] : ["ecoTransfers.returnDate"])].map((key) => <th key={key}>{t(key)}</th>)}
    </tr></thead><tbody>{rows.map((row) => <tr key={row.code}><td>{row.fabric_name}</td><td>{row.batch_no}</td><td>{row.color || "—"}</td><td>{row.roll_number}</td>
      <td className="whitespace-nowrap">{Number(row.quantity).toFixed(2)} {row.unit}</td><td>{removable ? <button type="button" className="btn" disabled={frozen || busy} aria-label={t("ecoTransfers.remove")} onClick={() => setDraft((rows) => rows.filter((r) => r.code !== row.code))}><Trash2 size={15}/></button> : row.returned_at ? <span>{new Date(row.returned_at).toLocaleString()}<br/>{row.return_operator_name}</span> : t("ecoTransfers.atEco")}</td>
    </tr>)}</tbody></table></div>;
  }
  if (!me) return <p>{t("common.loading")}</p>;
  if (!permitted) return <p role="alert">{t("ecoTransfers.denied")}</p>;
  return <div className="space-y-5">
    <PageHeader title={t("ecoTransfers.title")} subtitle={t("ecoTransfers.description")}/>
    <section className="card p-4 space-y-4">
      <fieldset disabled={busy || sending || frozen || returnRetry} className="flex flex-wrap gap-4"><legend className="mb-2 font-semibold">{t("fabricScans.mode")}</legend>
        {(["send", "return"] as const).map((value) => <label className="flex min-h-10 items-center gap-2" key={value}><input type="radio" name="eco-mode" checked={mode === value} onChange={() => { clearTimeout(timer.current); setCode(""); setMode(value); setMessage(""); }}/>{t(`ecoTransfers.${value}`)}</label>)}
      </fieldset>
      <form onSubmit={(event) => { event.preventDefault(); void scan(code); }}>
        <label htmlFor="eco-roll-code" className="label">{t("fabricScans.scanLabel")}</label>
        <div className="flex flex-wrap gap-2"><input ref={input} id="eco-roll-code" className="input min-h-12 flex-1" autoFocus autoComplete="off" value={code} disabled={frozen || sending || camera || returnRetry}
          placeholder={t("fabricScans.scanHint")} onChange={(event) => { setCode(event.target.value); clearTimeout(timer.current); if (isFabricRollCode(event.target.value)) timer.current = setTimeout(() => void scan(event.target.value), 250); }}/>
          <button className="btn" type="submit" disabled={frozen || sending || returnRetry}>{t("ecoTransfers.scan")}</button>
          <button className="btn" type="button" disabled={busy || frozen || returnRetry} onClick={() => setCamera(true)}><Camera size={16}/>{t("fabricScans.camera")}</button></div>
      </form>
      {camera && <FabricRollCamera onScan={scan} onClose={() => setCamera(false)}/>}
      {mode === "send" && <><h2 className="font-semibold">{t("ecoTransfers.draft")} · {draft.length} {t("fabricScans.rolls")} · {draft.reduce((sum, r) => sum + Number(r.quantity), 0).toFixed(2)} kg</h2>
        {draft.length ? rollTable(draft, true) : <p className="text-sm">{t("ecoTransfers.emptyDraft")}</p>}
        <button className="btn btn-primary" type="button" disabled={!draft.length || busy || sending} onClick={() => void send()}>{t(sending ? "fabricScans.saving" : frozen ? "ecoTransfers.retrySend" : "ecoTransfers.markSent")}</button></>}
      {busy && <p role="status">{t("fabricScans.saving")}</p>}
      {message && <p role="status" className="text-sm font-semibold">{message}</p>}
      {failure && <p role="alert" className="text-sm text-red-700">{failure}</p>}
      {returnRetry && <button className="btn" disabled={busy} onClick={async () => { if (!returnAttempt.current) return; setBusy(true); try { await completeReturn(returnAttempt.current); setFailure(""); } catch (err) { fail(err); } finally { setBusy(false); } }}>{t("ecoTransfers.retryReturn")}</button>}
      {lastDispatch && <button className="btn" onClick={() => void download(lastDispatch)}><Download size={16}/>{lastDispatch.number} · PDF</button>}
    </section>
    <section className="card p-4 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="font-semibold">{t("ecoTransfers.history")}</h2><p className="mt-1 text-sm">{t("ecoTransfers.outstanding")}: <strong>{data?.outstanding_rolls ?? "—"}</strong> {t("fabricScans.rolls")} · {Number(data?.outstanding_kg || 0).toFixed(2)} kg</p></div>
        <label className="label">{t("ecoTransfers.sentDate")}<input className="input" type="date" value={day} onChange={(event) => { setDay(event.target.value); setPage(1); }}/></label></div>
      {isLoading && <p>{t("common.loading")}</p>}{error && <p role="alert">{t("ecoTransfers.failed")}</p>}
      {data?.items.length === 0 && <p>{t("ecoTransfers.emptyHistory")}</p>}
      {data?.items.map((dispatch) => <details className="border-t pt-3" key={dispatch.id}>
        <summary className="cursor-pointer py-2 text-sm"><strong>{dispatch.number}</strong> · {new Date(dispatch.sent_at).toLocaleString()} · {dispatch.operator_name} · {t("ecoTransfers.sentCount")}: {dispatch.sent_rolls} / {Number(dispatch.sent_kg).toFixed(2)} kg · {t("ecoTransfers.outstanding")}: {dispatch.outstanding_rolls} / {Number(dispatch.outstanding_kg).toFixed(2)} kg</summary>
        <div className="py-3"><button className="btn mb-3" onClick={() => void download(dispatch)}><Download size={16}/>PDF</button>{rollTable(dispatch.rows)}</div>
      </details>)}
      {!!data?.total && <div className="flex items-center justify-end gap-3"><button className="btn" disabled={page === 1} onClick={() => setPage(page-1)}>{t("common.previous")}</button><span>{page} / {Math.ceil(data.total/30)}</span><button className="btn" disabled={page*30>=data.total} onClick={() => setPage(page+1)}>{t("common.next")}</button></div>}
    </section>
  </div>;
}
