"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { useDialogs } from "@/components/DialogProvider";
import { statusLabel } from "@/components/StagePipeline";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { stocktakeText } from "@/lib/stocktakeText";
import { useScannerFocus } from "@/lib/useScannerFocus";
import { addStocktakePending, migrateStocktakePending, readStocktakePending, removeStocktakePending, stocktakePendingPrefix, type PendingStocktakeScan } from "@/lib/stocktakeRecovery";

type Snapshot = { package_no?: string; barcode?: string; model_code?: string; color?: string; quantity?: number; available?: number; reserved?: number; status?: string; location?: string; items?: { model_code?: string; model_name?: string; color?: string; size?: string; quantity?: number }[] };
type Result = "found" | "missing" | "unknown" | "unexpected" | "ambiguous";
type Row = { id: number; package_id: number | null; result: Result; snapshot: Snapshot; scan_snapshot: Snapshot | null; scanned_pieces: number | null; scan_evidence_source: "scan" | "count_start" | "unresolved"; current: Snapshot | null; changed: boolean; scan_code: string | null; scanned_at: string | null };
type Detail = { title: string; created_at: string; completed_at: string | null; summary: Record<string, number>; total: number; rows: Row[] };

export default function StocktakeSession({ countId, userId, onBack }: { countId: number; userId: number; onBack: () => void }) {
  const { lang, t } = useT();
  const text = stocktakeText[lang];
  const { ask } = useDialogs();
  const [filter, setFilter] = useState("scanned");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const base = `/api/warehouse-stocktakes/${countId}`;
  const { data, error, mutate, isValidating } = useSWR<Detail>(`${base}?result=${filter}&q=${encodeURIComponent(search)}&offset=${offset}`, fetcher, { refreshInterval: 15000, keepPreviousData: true });
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(0);
  const [unsaved, setUnsaved] = useState<string[]>([]);
  const [failure, setFailure] = useState("");
  const [feedback, setFeedback] = useState<{ duplicate: boolean; row: Row } | null>(null);
  const [busy, setBusy] = useState(false);
  const queue = useRef<PendingStocktakeScan[]>([]);
  const saving = useRef(false);
  const failed = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const completed = !!data?.completed_at;
  const storageKey = stocktakePendingPrefix(userId, countId);
  const appendScanCharacter = useCallback((character: string) => setCode(value => (value + character).slice(0, 512)), []);
  useScannerFocus(input, !!data && !completed && !busy, appendScanCharacter);

  const refreshQueue = useCallback(() => {
    queue.current = readStocktakePending(localStorage, storageKey);
    setPending(queue.current.length); setUnsaved(queue.current.map(scan => scan.code));
  }, [storageKey]);

  useEffect(() => {
    mounted.current = true;
    try {
      migrateStocktakePending(localStorage, sessionStorage, userId, countId);
      refreshQueue();
      if (queue.current.length) { failed.current = true; setFailure(text.recovered); }
    } catch { failed.current = true; setFailure(text.storageError); }
    const sync = (event: StorageEvent) => {
      if (event.storageArea !== localStorage || (event.key !== null && !event.key.startsWith(storageKey))) return;
      try {
        refreshQueue();
        if (queue.current.length && !saving.current) { failed.current = true; setFailure(text.recovered); }
        else if (!queue.current.length) { failed.current = false; setFailure(""); }
      } catch { failed.current = true; setFailure(text.storageError); }
    };
    window.addEventListener("storage", sync);
    return () => { mounted.current = false; window.removeEventListener("storage", sync); };
  // Restore once for this user/count. Changing language must not overwrite a live scan queue.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, refreshQueue, userId, countId]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (queue.current.length) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  async function drain() {
    if (saving.current || failed.current || completed) return;
    saving.current = true;
    while (mounted.current && queue.current.length) {
      const scan = queue.current[0];
      try {
        const result = await api.post<{ duplicate: boolean; row: Row }>(`${base}/scan`, { code: scan.code });
        removeStocktakePending(localStorage, storageKey, scan.id);
        if (!mounted.current) break;
        setFeedback(result);
        refreshQueue();
        // Show persisted history after each acknowledgement, even during a long scan run.
        void mutate();
      } catch (e) {
        failed.current = true;
        if (mounted.current) { setPending(queue.current.length); setUnsaved(queue.current.map(item => item.code)); setFailure(e instanceof Error ? e.message : String(e)); }
        break;
      }
    }
    saving.current = false;
    if (mounted.current) void mutate();
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!code.trim() || completed || busy) return;
    try {
      addStocktakePending(localStorage, storageKey, { id: crypto.randomUUID(), code: code.trim(), createdAt: Date.now() });
      refreshQueue();
    } catch { setFailure(text.storageError); return; }
    setCode("");
    void drain(); input.current?.focus();
  }

  async function action(path: string, confirmation: string, remove = false) {
    if (queue.current.length || saving.current || busy) return;
    // Block scanner input while the confirmation is open as well as during the request.
    setBusy(true);
    try {
      if (!await ask(confirmation)) return;
      refreshQueue();
      if (queue.current.length) { failed.current = true; setFailure(text.recovered); return; }
      setFailure("");
      if (remove) await api.del(path); else await api.post(path, undefined, 60000);
      setFeedback(null);
      await mutate();
    } catch (e) { setFailure(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); input.current?.focus(); }
  }

  const resultLabel = (result: Result) => result === "missing" && completed ? text.missingFinal : text[result];
  const lastScan = feedback?.row;
  const lastSnapshot = lastScan?.scan_snapshot || lastScan?.snapshot;
  const contents = (snapshot: Snapshot | undefined) => snapshot?.items?.length ? <ul className="space-y-1 text-sm">{snapshot.items.map((item, index) => <li key={index}>
    {item.model_code || item.model_name || text.unresolvedModel}{item.color ? ` · ${item.color}` : ""}{item.size ? ` · ${item.size}` : ""} · {text.qty}: {item.quantity ?? text.unresolvedPieces}
  </li>)}</ul> : <span>{snapshot?.model_code || text.unresolvedModel}{snapshot?.color ? ` · ${snapshot.color}` : ""}</span>;
  return <section className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <button className="btn" disabled={pending > 0 || busy} onClick={onBack}>{text.back}</button>
      <div className="flex flex-wrap gap-2">
        <a className="btn" href={`${base}/export.csv`}>{text.download}</a>
        {data && !completed && <button className="btn btn-primary" disabled={pending > 0 || busy} onClick={() => void action(`${base}/complete`, text.finishConfirm)}>{text.finish}</button>}
      </div>
    </div>
    {(failure || error) && <p role="alert" className="text-red-700 break-words">{failure || String(error)}</p>}
    {!data && !error && <p>{text.loading}</p>}
    {data && <>
      <div><h2 className="text-lg font-medium">{data.title}</h2><p className="text-sm text-slate-500">{new Date(data.created_at).toLocaleString()} · {completed ? text.complete : text.open}</p></div>
      <p className="text-sm">{text.snapshot}</p>
      {!completed && <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 flex-1 min-w-48">{text.scan}<input ref={input} autoFocus className="input font-mono" value={code} onChange={e => setCode(e.target.value)} maxLength={512} autoComplete="off" disabled={busy} /></label>
        <button className="btn btn-primary" disabled={busy || !code.trim()}>{text.add}</button>
      </form>}
      {!completed && <p className="text-sm text-slate-500">{text.scannerReady}</p>}
      {pending > 0 && <div role="status" className="space-y-2"><span>{text.pending}: {pending}</span>{failure && <>
        <textarea className="input w-full font-mono" aria-label={text.pending} readOnly value={unsaved.join("\n")} />
        <div className="flex flex-wrap gap-2"><button className="btn" disabled={completed} onClick={() => { failed.current = false; setFailure(""); void drain(); }}>{text.retry}</button>
        <button className="btn" disabled={busy} onClick={async () => {
          if (saving.current || busy) return;
          setBusy(true);
          try {
            if (!await ask(text.discardConfirm)) return;
            const discarded = [...queue.current];
            discarded.forEach(scan => removeStocktakePending(localStorage, storageKey, scan.id));
            refreshQueue(); failed.current = false; setFailure("");
          } catch { setFailure(text.storageError); }
          finally { setBusy(false); }
        }}>{text.discard}</button></div>
      </>}</div>}
      {feedback && lastScan && <div role="status" aria-live="polite" aria-atomic="true" className="border-l-2 border-current pl-3 py-1 space-y-1">
        <p className={lastScan.result === "found" ? "text-green-700" : "text-amber-800"}>{feedback.duplicate ? text.duplicate : `${text.saved} · ${resultLabel(lastScan.result)}`}</p>
        <p><span className="font-medium">{lastSnapshot?.package_no || lastScan.scan_code}</span> · {text.qty}: <strong>{lastScan.scanned_pieces ?? text.unresolvedPieces}</strong></p>
        {contents(lastSnapshot)}
        {lastScan.scan_evidence_source === "count_start" && <p className="text-sm text-amber-800">{text.estimatedScan}</p>}
      </div>}
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-base"><span>{text.scannedPackages}: <strong>{data.summary.scanned_packages}</strong></span><span>{text.scannedPieces}: <strong>{data.summary.scanned_pieces}</strong></span></div>
      {data.summary.estimated_packages > 0 && <p className="text-sm text-amber-800">{text.estimatedTotal}: {data.summary.estimated_packages}</p>}
      {data.summary.unquantified_packages > 0 && <p className="text-sm text-amber-800">{text.unquantifiedTotal}: {data.summary.unquantified_packages}</p>}
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-y py-3 text-sm"><span>{text.expected}: <b>{data.summary.expected}</b></span><span>{text.scanned}: <b>{data.summary.scanned}</b></span><span>{text.found}: <b>{data.summary.found}</b></span><span>{completed ? text.missingFinal : text.missing}: <b>{data.summary.missing}</b></span><span>{text.unknown}: <b>{data.summary.unknown}</b></span><span>{text.unexpected}: <b>{data.summary.unexpected}</b></span><span>{text.ambiguous}: <b>{data.summary.ambiguous}</b></span><span>{text.changed}: <b>{data.summary.changed}</b></span></div>
      {data.summary.changed > 0 && <p className="text-amber-800 text-sm">{text.movement}</p>}
      {(data.summary.unknown > 0 || data.summary.ambiguous > 0) && <p className="text-sm">{text.unknownHelp}</p>}
      <div className="flex flex-wrap gap-3 items-end">
        <label className="flex flex-col gap-1">{text.result}<select className="input" value={filter} onChange={e => { setFilter(e.target.value); setOffset(0); input.current?.focus({ preventScroll: true }); }}>
          {["scanned", "all", "found", "missing", "unknown", "unexpected", "ambiguous", "changed"].map(key => <option key={key} value={key}>{key === "scanned" ? text.scanHistory : key === "missing" && completed ? text.missingFinal : text[key as keyof typeof text]}</option>)}
        </select></label>
        <form className="flex min-w-48 flex-wrap gap-2 items-end flex-1" onSubmit={e => { e.preventDefault(); setSearch(query); setOffset(0); input.current?.focus({ preventScroll: true }); }}><label className="flex flex-col gap-1 flex-1 min-w-48">{text.search}<input className="input" value={query} onChange={e => setQuery(e.target.value)} maxLength={120} /></label><button className="btn">{t("common.search")}</button></form>
      </div>
      <p className="text-sm text-slate-500">{text.historySaved}</p>
      <div className="overflow-x-auto border-y" aria-busy={isValidating}><table className="table"><thead><tr><th>{text.result}</th><th>{text.package}</th><th>{text.model}</th><th>{text.qty}</th><th>{text.location}</th><th>{text.status}</th><th>{text.scannedAt}</th><th /></tr></thead><tbody>
        {data.rows.map(row => <tr key={row.id}>
          <td><span className={row.result === "found" ? "text-green-700" : row.result === "missing" ? "" : "text-amber-800"}>{resultLabel(row.result)}</span>{row.changed && <span className="block text-sm text-amber-800">{text.changed}</span>}</td>
          <td className="break-all">{row.package_id ? <Link className="underline" href={`/packages/${row.package_id}`} target="_blank" rel="noreferrer">{row.snapshot.package_no}</Link> : row.scan_code}<span className="block text-xs text-slate-500">{row.snapshot.barcode}</span></td>
          <td>{contents(row.scan_snapshot || row.snapshot)}</td><td>{row.scanned_at ? row.scanned_pieces ?? "—" : row.snapshot.quantity ?? "—"}{row.scan_evidence_source === "count_start" && <span className="block text-xs text-amber-800">{text.estimatedScan}</span>}{row.package_id && <span className="block text-xs">{t("field.available")}: {row.snapshot.available} · {t("field.reserved")}: {row.snapshot.reserved}</span>}{row.changed && <span className="block text-xs">{text.current}: {row.current?.quantity ?? "—"} · {t("field.available")}: {row.current?.available ?? "—"} · {t("field.reserved")}: {row.current?.reserved ?? "—"}</span>}</td>
          <td>{row.snapshot.location || "—"}</td><td>{row.snapshot.status ? statusLabel(row.snapshot.status, t) : "—"}{row.changed && <span className="block text-sm">{text.current}: {row.current?.status ? statusLabel(row.current.status, t) : text.deleted}{row.current?.location ? ` · ${row.current.location}` : ""}</span>}</td>
          <td className="whitespace-nowrap">{row.scanned_at ? new Date(row.scanned_at).toLocaleString() : "—"}</td>
          <td>{!completed && row.scanned_at && <button className="btn" disabled={pending > 0 || busy} onClick={() => void action(`${base}/scans/${row.id}`, text.undoConfirm, true)}>{text.undo}</button>}</td>
        </tr>)}
        {data.rows.length === 0 && <tr><td colSpan={8}>{text.noRows}</td></tr>}
      </tbody></table></div>
      <div className="flex gap-3 items-center"><button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>{text.previous}</button><span>{data.total ? offset + 1 : 0}–{Math.min(offset + 100, data.total)} / {data.total}</span><button className="btn" disabled={offset + 100 >= data.total} onClick={() => setOffset(offset + 100)}>{text.next}</button></div>
    </>}
  </section>;
}
