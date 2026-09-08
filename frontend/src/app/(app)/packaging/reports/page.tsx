"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { Download, RefreshCw } from "lucide-react";
import useSWR from "swr";

import PageHeader from "@/components/PageHeader";
import PackagingReportTable from "@/components/PackagingReportTable";
import { fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { packagingReportColumns, type PackagingReport } from "@/lib/packagingReport";

function today() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  return ["year", "month", "day"].map((key) => parts.find((part) => part.type === key)?.value).join("-");
}

export default function PackagingReportsPage() {
  const { t, lang } = useT();
  const { me } = useMe();
  const searchParams = useSearchParams();
  const department = searchParams.get("packaging_department") || "PKG";
  const factory = department === "ECP" ? "Eco Cotton" : department === "BPK" ? "Besttex" : "Milana";
  const [fromDate, setFromDate] = useState(() => `${today().slice(0, 7)}-01`);
  const [toDate, setToDate] = useState(today);
  const [tab, setTab] = useState<keyof typeof packagingReportColumns>("daily");
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const validDates = Boolean(fromDate && toDate && fromDate <= toDate);
  const params = new URLSearchParams({ from_date: fromDate, to_date: toDate, packaging_department_code: department });
  const reportUrl = `/api/packaging/reports?${params}`;
  const { data, error, isLoading, mutate } = useSWR<PackagingReport>(
    validDates && can(me, "packaging.records", "packaging.packages", "planning.production") ? reportUrl : null,
    fetcher, { shouldRetryOnError: false },
  );

  async function download() {
    setDownloadError("");
    setDownloading(true);
    try {
      const response = await fetch(`/api/packaging/reports/export.xlsx?${params}&lang=${lang}`, { credentials: "same-origin" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(typeof payload?.detail === "string" ? payload.detail : t("packagingReport.downloadFailed"));
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `packaging_${department}_${fromDate}_${toDate}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (downloadFailure) {
      setDownloadError(downloadFailure instanceof Error ? downloadFailure.message : t("packagingReport.downloadFailed"));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div>
      <PageHeader title={`${factory} — ${t("packagingReport.title")}`} subtitle={t("packagingReport.dateHint")} />
      <section className="card p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="packaging-report-from" className="label">{t("packagingReport.from")}</label>
            <input id="packaging-report-from" type="date" className="input" value={fromDate} max={toDate || undefined} onChange={(event) => setFromDate(event.target.value)} />
          </div>
          <div>
            <label htmlFor="packaging-report-to" className="label">{t("packagingReport.to")}</label>
            <input id="packaging-report-to" type="date" className="input" value={toDate} min={fromDate || undefined} onChange={(event) => setToDate(event.target.value)} />
          </div>
          <button type="button" className="btn" disabled={!validDates || isLoading} onClick={() => mutate()}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />{t("btn.refresh")}
          </button>
          <button type="button" className="btn btn-primary" disabled={!validDates || !data || Boolean(error) || downloading} onClick={download}>
            <Download className="h-4 w-4" aria-hidden="true" />{t(downloading ? "common.loading" : "packagingReport.excel")}
          </button>
        </div>
        {!validDates && <p role="alert" className="mt-3 text-sm text-red-700">{t("packagingReport.invalidDates")}</p>}
        {(error || downloadError) && <p role="alert" className="mt-3 text-sm text-red-700">{downloadError || error?.message || t("packagingReport.loadFailed")}</p>}
        <div className="mt-5 flex flex-wrap gap-4 border-b border-[#e3dfd3]" role="tablist" aria-label={t("packagingReport.title")}>
          {(["daily", "entries", "completed"] as const).map((key) => (
            <button key={key} id={`report-tab-${key}`} type="button" role="tab" aria-selected={tab === key} aria-controls="packaging-report-panel"
              className={`border-b-2 px-1 py-2 text-sm ${tab === key ? "border-[#14110b] font-semibold text-[#14110b]" : "border-transparent text-[#6d6758]"}`}
              onClick={() => setTab(key)}>{t(`packagingReport.${key}`)}</button>
          ))}
        </div>
        <details className="my-3 max-w-5xl text-sm text-[#6d6758]">
          <summary className="cursor-pointer">{t("packagingReport.notes")}</summary>
          <p className="mt-2">{t("packagingReport.note")}</p>
        </details>
        <div id="packaging-report-panel" role="tabpanel" aria-labelledby={`report-tab-${tab}`}>
          {isLoading && <p role="status" className="py-6 text-sm">{t("common.loading")}</p>}
          {!isLoading && validDates && !error && data && (
            <PackagingReportTable key={`${reportUrl}:${tab}`} rows={data[tab]} columns={packagingReportColumns[tab]} pictures={tab === "entries"} />
          )}
        </div>
      </section>
    </div>
  );
}
