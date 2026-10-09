"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { logout, type Me } from "@/lib/auth";
import { useT, type Lang } from "@/lib/i18n";
import { sewingBandText, type Band, type BandJob } from "@/lib/sewingBandText";
import BandProgress from "./BandProgress";

type Report = { id: number; work_order_id: number; sewing_assignment_id: number; sewn_qty: number; top_qty: number | null; bottom_qty: number | null; defective_qty: number; defect_reason: string | null; notes: string | null; order_no: string; report_date: string };
type Option = { production_order_id: number; production_batch_id: number | null; order_no: string; model_code: string; batch_label: string; quantity: number };
const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());

export default function BandWorkspace({ me }: { me: Me }) {
  const { lang, setLang } = useT(); const text = sewingBandText(lang); const pathname = usePathname();
  const reporting = pathname.includes("daily-report"); const receiving = pathname.includes("bundles");
  const { data, error: loadError, mutate } = useSWR<Band[]>("/api/sewing-bands", fetcher, { refreshInterval: 10000 });
  const band = data?.[0]; const jobs = band?.jobs || [];
  const [date, setDate] = useState(today); const [jobId, setJobId] = useState("");
  const [sewn, setSewn] = useState(""); const [twoPart, setTwoPart] = useState(false);
  const [top, setTop] = useState(""); const [bottom, setBottom] = useState("");
  const [defects, setDefects] = useState("0"); const [reason, setReason] = useState(""); const [notes, setNotes] = useState("");
  const [editing, setEditing] = useState<Report | null>(null);
  const busyRef = useRef(false);
  const pendingWrites = useRef(new Map<string, string>());
  async function postOnce<T = unknown>(url: string, body: unknown): Promise<T> {
    const fingerprint = JSON.stringify([url, body]);
    const key = pendingWrites.current.get(fingerprint) || crypto.randomUUID();
    pendingWrites.current.set(fingerprint, key);
    const result = await api.postWithHeaders<T>(url, body, { "Idempotency-Key": key });
    pendingWrites.current.delete(fingerprint);
    return result;
  }
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [message, setMessage] = useState("");
  const [code, setCode] = useState(""); const [search, setSearch] = useState(""); const [options, setOptions] = useState<Option[] | null>(null);
  const [output, setOutput] = useState<BandJob | null>(null); const [passed, setPassed] = useState(""); const [failed, setFailed] = useState("0");
  const { data: reports, error: reportError, mutate: refreshReports } = useSWR<{ rows: Report[] }>(reporting ? `/api/sewing-daily-reports?report_date=${date}` : null, fetcher);
  const refresh = () => { void mutate(); void refreshReports(); };
  async function run(action: () => Promise<void>) {
    if (busyRef.current) return; busyRef.current = true; setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (err) { setError(String(err)); } finally { busyRef.current = false; setBusy(false); }
  }
  function clearReport() { setEditing(null); setSewn(""); setTop(""); setBottom(""); setDefects("0"); setReason(""); setNotes(""); }
  async function receive(body: unknown) {
    await run(async () => { const result = await api.post<{ already_accepted?: boolean }>("/api/sewing-bands/receive", body); setMessage(result.already_accepted ? text.repeated : text.received); setCode(""); setOptions(null); refresh(); });
  }
  const links: [string, string][] = [["/departments/ECO", text.floor], ["/sewing/flows?factory=ECO", text.flows], ["/sewing/daily-report?factory=ECO", text.report], ["/bundles/scan/sewing?factory=ECO", text.receive]];
  return <div className="min-h-screen bg-stone-100 text-stone-900">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-300 bg-white px-4 py-3">
      <h1 className="text-xl font-semibold">Eco Cotton · {band?.name || me.name}</h1>
      <div className="flex items-center gap-3"><label>{text.language}{" "}<select className="input" value={lang} onChange={e => setLang(e.target.value as Lang)}><option value="en">English</option><option value="ru">Русский</option><option value="uz">O‘zbekcha</option></select></label><button className="btn" onClick={logout}>{text.logout}</button></div>
    </header>
    <nav className="flex flex-wrap gap-2 border-b border-stone-300 bg-white p-3">{links.map(([href, label]) => <Link className="btn" key={href} href={href} aria-current={pathname === href.split("?")[0] ? "page" : undefined}>{label}</Link>)}</nav>
    <main className="mx-auto max-w-4xl space-y-4 p-4">
      {(error || loadError || reportError) && <p role="alert" className="text-red-700">{error || String(loadError || reportError)}</p>}
      {message && <p role="status">{message}</p>}
      {!band && !loadError && <p>{text.loading}</p>}
      {receiving && <section className="card space-y-4 p-4">
        <h2 className="text-lg font-semibold">{text.receive}</h2>
        <form onSubmit={e => { e.preventDefault(); void receive({ code }); }} className="space-y-2">
          <label className="block">{text.scan}<input autoFocus className="input mt-1 w-full" value={code} onChange={e => setCode(e.target.value)} required /></label>
          <button className="btn" disabled={busy}>{text.receiveButton}</button>
        </form>
        <form className="space-y-2" onSubmit={e => { e.preventDefault(); void run(async () => setOptions(await api.get<Option[]>(`/api/sewing-bands/receive-options?q=${encodeURIComponent(search)}`))); }}>
          <label className="block">{text.search}<input className="input mt-1 w-full" value={search} onChange={e => setSearch(e.target.value)} /></label><button className="btn" disabled={busy}>{text.searchButton}</button>
        </form>
        {options?.length === 0 && <p>{text.emptyReceive}</p>}
        {options?.map(o => <div key={`${o.production_order_id}:${o.production_batch_id}`} className="flex flex-wrap items-center justify-between gap-3 border-t py-3"><span>{o.order_no} · {o.model_code} · {o.batch_label} · {o.quantity}</span><button className="btn" disabled={busy} onClick={() => void receive({ production_order_id: o.production_order_id, production_batch_id: o.production_batch_id })}>{text.receiveButton}</button></div>)}
      </section>}
      {reporting && <section className="card space-y-4 p-4">
        <h2 className="text-lg font-semibold">{text.report} · {band?.name}</h2>
        <form className="space-y-3" onSubmit={e => { e.preventDefault(); void run(async () => {
          const job = jobs.find(j => String(j.id) === jobId);
          if (!job && !editing) throw new Error(text.choose);
          const body = { report_date: date, sewn_qty: twoPart ? Number(top) + Number(bottom) : Number(sewn), top_qty: twoPart ? Number(top) : null, bottom_qty: twoPart ? Number(bottom) : null, defective_qty: Number(defects), defect_reason: reason || null, notes: notes || null };
          if (editing) await api.patch(`/api/sewing-daily-reports/${editing.id}`, body);
          else await postOnce("/api/sewing-daily-reports", { ...body, sewing_flow_id: me.sewing_band_id, work_order_id: job!.work_order_id, sewing_assignment_id: job!.id });
          clearReport(); setMessage(text.saved); refresh();
        }); }}>
          <label className="block">{text.date}<input className="input ml-2" type="date" value={date} onChange={e => setDate(e.target.value)} required /></label>
          {editing ? <p>{editing.order_no}</p> : <label className="block">{text.choose}<select aria-label={text.choose} className="input mt-1 w-full" value={jobId} onChange={e => setJobId(e.target.value)} required><option value="">{text.choose}</option>{jobs.filter(j => !j.line_finished).map(j => <option key={j.id} value={j.id}>{j.order_no} · {j.model} · {j.batch}</option>)}</select></label>}
          <p className="text-sm text-stone-600">{text.reportHint}</p>
          <label className="flex gap-2"><input type="checkbox" checked={twoPart} onChange={e => setTwoPart(e.target.checked)} />{text.twoPart}</label>
          <div className="grid gap-3 sm:grid-cols-2">{twoPart ? <><label>{text.top}<input className="input mt-1 w-full" type="number" min="0" step="1" required value={top} onChange={e => setTop(e.target.value)} /></label><label>{text.bottom}<input className="input mt-1 w-full" type="number" min="0" step="1" required value={bottom} onChange={e => setBottom(e.target.value)} /></label></> : <label>{text.sewn}<input className="input mt-1 w-full" type="number" min="1" step="1" required value={sewn} onChange={e => setSewn(e.target.value)} /></label>}
          <label>{text.defects}<input className="input mt-1 w-full" type="number" min="0" step="1" required value={defects} onChange={e => setDefects(e.target.value)} /></label></div>
          {Number(defects) > 0 && <label className="block">{text.reason}<input className="input mt-1 w-full" value={reason} onChange={e => setReason(e.target.value)} required /></label>}
          <label className="block">{text.notes}<input className="input mt-1 w-full" value={notes} onChange={e => setNotes(e.target.value)} /></label>
          <button className="btn" disabled={busy}>{text.save}</button>{editing && <button className="btn ml-2" type="button" onClick={clearReport}>{text.cancel}</button>}
        </form>
        {reports?.rows?.length === 0 && <p>{text.noReports}</p>}
        {reports?.rows?.map(r => <div className="flex flex-wrap justify-between gap-2 border-t py-2" key={r.id}><span>{r.order_no} · {r.sewn_qty}</span><button className="btn" disabled={busy} onClick={() => { setEditing(r); setJobId(String(r.sewing_assignment_id)); setDate(r.report_date); setSewn(String(r.sewn_qty)); setTwoPart(r.top_qty !== null); setTop(String(r.top_qty ?? "")); setBottom(String(r.bottom_qty ?? "")); setDefects(String(r.defective_qty)); setReason(r.defect_reason || ""); setNotes(r.notes || ""); }}>{text.edit}</button></div>)}
      </section>}
      {!reporting && !receiving && band && <section className="card p-4"><h2 className="text-lg font-semibold">{pathname.includes("flows") ? text.flows : text.floor} · {band.name}</h2><BandProgress jobs={jobs} onOutput={job => { setOutput(job); setPassed(""); setFailed("0"); setReason(""); }} /></section>}
      {output && !reporting && !receiving && <section className="card space-y-3 p-4"><h2 className="text-lg font-semibold">{output.order_no} · {text.final}</h2><p>{text.finalHint}</p><p>{text.discrepancy}: {output.reported_qty} / {output.actual_qty}</p>
        <form className="space-y-3" onSubmit={e => { e.preventDefault(); void run(async () => {
          await postOnce(`/api/sewing-bands/${output.id}/output`, { work_order_id: output.work_order_id, production_batch_id: output.production_batch_id, sewing_assignment_id: output.id, input_qty: 0, sewn_qty: Number(passed) + Number(failed), passed_qty: Number(passed), failed_qty: Number(failed), defect_reason: reason || null });
          setOutput(null); setMessage(text.saved); refresh();
        }); }}>
          <label className="block">{text.passed}<input className="input ml-2" type="number" min="0" required value={passed} onChange={e => setPassed(e.target.value)} /></label>
          <label className="block">{text.failed}<input className="input ml-2" type="number" min="0" required value={failed} onChange={e => setFailed(e.target.value)} /></label>
          {Number(failed) > 0 && <label className="block">{text.reason}<input className="input ml-2" required value={reason} onChange={e => setReason(e.target.value)} /></label>}
          <button className="btn" disabled={busy}>{text.finalSave}</button>{" "}<button type="button" className="btn" disabled={busy} onClick={() => setOutput(null)}>{text.close}</button>
        </form>
      </section>}
    </main>
  </div>;
}
