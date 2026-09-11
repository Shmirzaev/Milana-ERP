"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Camera, Download, RefreshCw } from "lucide-react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import FabricRollCamera from "@/components/FabricRollCamera";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { FABRIC_SCAN_PERMISSIONS, FABRIC_REPORT_PERMISSIONS, downloadFabricReport, isFabricRollCode, tashkentDate, type FabricDirection, type FabricReport, type FabricScanRow } from "@/lib/fabricScans";

export default function FabricScansPage() {
  const { t, lang } = useT();
  const { me } = useMe();
  const [direction, setDirection] = useState<FabricDirection>("received");
  const [code, setCode] = useState("");
  const [day, setDay] = useState(tashkentDate);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [busy, setBusy] = useState(false);
  const [camera, setCamera] = useState(false);
  const [message, setMessage] = useState("");
  const [scanError, setScanError] = useState("");
  const [failedScans, setFailedScans] = useState<{ code: string; direction: FabricDirection }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const queue = useRef(Promise.resolve());
  const pending = useRef(0);
  const scanTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(scanTimer.current), []);
  const permitted = me?.factory_code !== "BST" && can(me, ...FABRIC_REPORT_PERMISSIONS);
  const canScan = permitted && can(me, ...FABRIC_SCAN_PERMISSIONS);
  const { data, error, isLoading, isValidating, mutate } = useSWR<FabricReport>(
    permitted && day ? [`/api/fabric-scans?report_date=${day}&page=${page}&page_size=${pageSize}`, me?.factory_code] : null,
    ([url]: [string, string]) => fetcher(url), { shouldRetryOnError: false, refreshInterval: 30000 },
  );
  const time = new Intl.DateTimeFormat(lang, { timeZone: "Asia/Tashkent", hour: "2-digit", minute: "2-digit", second: "2-digit" });

  function save(value: string, action = direction): Promise<void> {
    clearTimeout(scanTimer.current);
    value = value.trim();
    if (!canScan || !value.trim()) return Promise.resolve();
    pending.current += 1;
    setBusy(true);
    setCode("");
    const task = queue.current.then(() => record(value, action));
    queue.current = task;
    return task;
  }
  async function record(value: string, action: FabricDirection) {
    setScanError("");
    setMessage("");
    try {
      const result = await api.post<{ duplicate: boolean; row: FabricScanRow }>("/api/fabric-scans", { code: value.trim(), direction: action });
      setMessage(`${t(result.duplicate ? "fabricScans.duplicate" : "fabricScans.saved")} · ${t(`fabricScans.${result.row.direction}`)} · ${result.row.fabric_name} · ${result.row.batch_no} · ${t("fabricScans.roll")} ${result.row.roll_number}`);
      setFailedScans((rows) => rows.filter((row) => row.code !== value || row.direction !== action));
      setDay(result.row.report_date);
      setPage(1);
      void mutate();
    } catch (err) {
      const text = err instanceof Error ? err.message : "";
      const key = ["invalid_roll_code", "fabric_not_found", "roll_not_found"].find((value) => text.includes(value));
      setScanError(t(key ? `fabricScans.${key}` : "fabricScans.saveError"));
      setFailedScans((rows) => rows.some((row) => row.code === value && row.direction === action) ? rows : [...rows, { code: value, direction: action }]);
    } finally {
      pending.current -= 1;
      setBusy(pending.current > 0);
      requestAnimationFrame(() => input.current?.focus());
    }
  }
  function submit(event: FormEvent) { event.preventDefault(); void save(code); }
  if (!me) return <p role="status">{t("common.loading")}</p>;
  if (!permitted) return <p role="alert">{t("fabricScans.denied")}</p>;

  return <div className="space-y-5">
    <PageHeader title={t("fabricScans.title")} subtitle={t("fabricScans.description")} />
    {canScan && <section className="card p-4">
      <fieldset disabled={busy}>
        <legend className="mb-3 font-semibold">{t("fabricScans.mode")}</legend>
        <div className="flex flex-wrap gap-3">
          {(["received", "returned"] as const).map((value) => <label key={value} className={`flex min-h-12 cursor-pointer items-center gap-3 rounded-md border px-4 py-3 ${direction === value ? "border-[#14110b] bg-[#f1efe8]" : "border-[#e3dfd3]"}`}>
            <input type="radio" name="direction" value={value} checked={direction === value} onChange={() => { clearTimeout(scanTimer.current); setCode(""); setDirection(value); setMessage(""); input.current?.focus(); }} />
            {t(`fabricScans.${value}`)}
          </label>)}
        </div>
      </fieldset>
      <form onSubmit={submit} className="mt-4">
        <label htmlFor="fabric-roll-code" className="label">{t("fabricScans.scanLabel")}</label>
        <div className="flex flex-wrap gap-2">
          <input ref={input} id="fabric-roll-code" className="input min-h-12 min-w-0 basis-full sm:flex-1 sm:basis-auto" autoFocus autoComplete="off" spellCheck={false}
            placeholder={t("fabricScans.scanHint")} value={code} disabled={camera} onChange={(event) => {
              const value = event.target.value;
              setCode(value);
              clearTimeout(scanTimer.current);
              // Enter-terminated scanners save immediately; others save after the input settles.
              if (isFabricRollCode(value)) scanTimer.current = setTimeout(() => void save(value), 250);
            }} />
          <button className="btn min-h-12" type="button" disabled={busy || camera} onClick={() => { clearTimeout(scanTimer.current); setCode(""); setCamera(true); }}><Camera className="h-4 w-4" />{t("fabricScans.camera")}</button>
        </div>
      </form>
      <p className="mt-3 text-sm font-semibold">{t(busy ? "fabricScans.saving" : "fabricScans.ready")}</p>
      <p className="mt-3 text-sm text-[#6d6758]">{t("fabricScans.dailyRule")}</p>
      {camera && <FabricRollCamera onScan={save} onClose={() => { setCamera(false); requestAnimationFrame(() => input.current?.focus()); }} />}
      {message && <p role="status" className="mt-3 text-sm font-semibold">{message}</p>}
      {scanError && <p role="alert" className="mt-3 text-sm text-red-700">{scanError}</p>}
      {failedScans.map((row) => <div key={`${row.direction}:${row.code}`} className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="min-w-0 break-all">{t("fabricScans.notSaved")} · {t(`fabricScans.${row.direction}`)} · {row.code}</span>
        <button type="button" className="btn" disabled={busy} onClick={() => void save(row.code, row.direction)}>{t("fabricScans.retry")}</button>
      </div>)}
    </section>}

    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-end gap-3 border-b border-[#e3dfd3] p-4">
        <div className="mr-auto"><h2 className="font-semibold">{t("fabricScans.report")}</h2><p className="mt-1 text-sm text-[#6d6758]">{t("fabricScans.reportHint")}</p></div>
        <div><label htmlFor="fabric-report-date" className="label">{t("fabricScans.date")}</label>
          <input id="fabric-report-date" className="input" type="date" value={day} onChange={(event) => { setDay(event.target.value); setPage(1); }} /></div>
        <button type="button" className="btn" disabled={!day || isValidating} onClick={() => void mutate()}><RefreshCw className="h-4 w-4" />{t("btn.refresh")}</button>
        <button type="button" className="btn" disabled={!data || isValidating || !!error} onClick={() => data && downloadFabricReport(data, t)}><Download className="h-4 w-4" />{t("fabricScans.export")}</button>
      </div>
      {isLoading && <p role="status" className="p-4">{t("common.loading")}</p>}
      {error && <p role="alert" className="p-4 text-red-700">{t("fabricScans.loadError")}</p>}
      {data && !error && <>
        <div className="flex flex-wrap gap-x-6 gap-y-2 p-4 text-sm">
          <span>{t("fabricScans.received")}: <strong className="font-semibold">{data.received} {t("fabricScans.rolls")}</strong></span>
          <span>{t("fabricScans.returned")}: <strong className="font-semibold">{data.returned} {t("fabricScans.rolls")}</strong></span>
        </div>
        {!data.total ? <p className="p-4 text-sm text-[#6d6758]">{t("fabricScans.empty")}</p> : <>
          <div className="overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="border-y border-[#e3dfd3] bg-[#f8f7f2]"><tr>{["fabric", "batch", "color", "received", "returned"].map((key) => <th className="px-4 py-3 font-semibold" key={key} scope="col">{t(`fabricScans.${key}`)}</th>)}</tr></thead>
            <tbody className="divide-y divide-[#ecebe3]">{data.summary.map((row, index) => <tr key={index}>
              <td className="min-w-40 px-4 py-3">{row.fabric_name}</td><td className="px-4 py-3">{row.batch_no}</td><td className="px-4 py-3">{row.color || "—"}</td><td className="px-4 py-3 tabular-nums">{row.received}</td><td className="px-4 py-3 tabular-nums">{row.returned}</td>
            </tr>)}</tbody>
          </table></div>
          <h3 className="px-4 pb-3 pt-5 font-semibold">{t("fabricScans.history")}</h3>
          <div className="overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="border-y border-[#e3dfd3] bg-[#f8f7f2]"><tr>{["time", "direction", "fabric", "batch", "roll", "worker"].map((key) => <th className="px-4 py-3 font-semibold" key={key} scope="col">{t(`fabricScans.${key}`)}</th>)}</tr></thead>
            <tbody className="divide-y divide-[#ecebe3]">{data.rows.map((row) => <tr key={row.id}>
              <td className="whitespace-nowrap px-4 py-3">{time.format(new Date(row.scanned_at))}</td><td className="px-4 py-3">{t(`fabricScans.${row.direction}`)}</td><td className="min-w-40 px-4 py-3">{row.fabric_name}</td><td className="px-4 py-3">{row.batch_no}</td><td className="px-4 py-3">{row.roll_number}</td><td className="px-4 py-3">{row.operator_name}</td>
            </tr>)}</tbody>
          </table></div>
          <PaginationControls page={page} pageSize={pageSize} total={data.total} count={data.rows.length} onPageChange={setPage}
            onPageSizeChange={(size) => { setPageSize(size); setPage(1); }} pageSizeOptions={[25, 50, 100, 200]} />
        </>}
      </>}
    </section>
  </div>;
}
