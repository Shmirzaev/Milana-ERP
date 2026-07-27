"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarDays,
  ClipboardList,
  FileSpreadsheet,
  FileText,
  Plus,
  RefreshCw,
  Save,
  Shirt,
  Trash2,
} from "lucide-react";
import useSWR from "swr";

import PageHeader from "@/components/PageHeader";
import DefectReasonSelect from "@/components/DefectReasonSelect";
import ManualModelIdentityFields, { type ManualModelIdentityValue } from "@/components/ManualModelIdentityFields";
import SewingWorkPicker, {
  SewingModelCell,
  sewingWorkKey,
  type SewingModelIdentity,
} from "@/components/SewingWorkPicker";
import { api, fetcher } from "@/lib/api";
import { defectReasonLabel } from "@/lib/defectReasons";
import { formatBatchLabel } from "@/lib/batchSerial";
import { useT } from "@/lib/i18n";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";

type Flow = {
  id: number;
  name: string;
  code: string;
  is_active: boolean;
};

type LineWorkOrder = SewingModelIdentity & {
  work_order_id: number;
  sewing_assignment_id: number | null;
  production_order_id: number;
  production_batch_id: number | null;
  batch_no?: string | null;
  batch_name?: string | null;
  batch_index?: number | null;
  order_no: string | null;
  production_no: string | null;
  sales_order_no: string | null;
  status: string;
  planned_qty: number;
  completed_qty: number;
  remaining_qty: number;
  deadline: string | null;
  kroy_no: string | null;
};

type LineContext = {
  sewing_flow_id: number;
  line_code: string;
  line_name: string;
  active_work_orders: LineWorkOrder[];
};

type ReportRow = SewingModelIdentity & {
  id: number;
  order_no: string | null;
  production_no: string | null;
  sales_order_no: string | null;
  line_code: string;
  line_name: string;
  sewn_qty: number;
  section_quantities: number[] | null;
  section_no: number | null;
  section_name: string | null;
  top_qty: number | null;
  bottom_qty: number | null;
  defective_qty: number;
  defect_reason: string | null;
  notes: string | null;
  kroy_no: string | null;
  created_at: string;
};

type SummaryLine = {
  sewing_flow_id: number;
  line_code: string;
  line_name: string;
  total_sewn_qty: number;
  total_defective_qty: number;
  orders: string[];
  models: SewingModelIdentity[];
  defect_reasons: string[];
  kroy_nos: string[];
};

type ReportList = {
  rows: ReportRow[];
  summary: SummaryLine[];
  total_sewn_qty: number;
  total_defective_qty: number;
};

type SectionEntry = {
  id: string;
  isTwoPart: boolean;
  workKey: string;
  sewnQty: NumberInputValue;
  topQty: NumberInputValue;
  bottomQty: NumberInputValue;
  defectiveQty: NumberInputValue;
  manualModel: ManualModelIdentityValue;
  kroyNo: string;
};

function createSectionEntry(): SectionEntry {
  return {
    id: crypto.randomUUID(),
    isTwoPart: false,
    workKey: "",
    sewnQty: "",
    topQty: "",
    bottomQty: "",
    defectiveQty: "",
    manualModel: { enabled: false, modelNo: "", variantNo: "" },
    kroyNo: "",
  };
}

function emptySectionEntries(): SectionEntry[] {
  return Array.from({ length: 3 }, createSectionEntry);
}

function todayInputDate() {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

function workBatchLabel(work: LineWorkOrder) {
  if (!work.production_batch_id) return "";
  return formatBatchLabel(
    {
      batch_no: work.batch_no,
      name: work.batch_name,
      batch_index: work.batch_index,
    },
    work.production_order_id,
  );
}

function defectRate(sewn: number, defective: number) {
  return sewn > 0 ? `${((defective / sewn) * 100).toFixed(1)}%` : "0%";
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}

const SECTIONED_LINE_CODES = new Set(["SEW-01", "SEW-06", "SEW-07", "SEW-09"]);
const MAX_SECTION_COUNT = 20;

export default function SewingDailyReportPage() {
  const { t, lang } = useT();
  const [reportDate, setReportDate] = useState(todayInputDate());
  const [exportFromDate, setExportFromDate] = useState(todayInputDate());
  const [exportToDate, setExportToDate] = useState(todayInputDate());
  const [downloadingReport, setDownloadingReport] = useState<"xlsx" | "pdf" | null>(null);
  const [exportError, setExportError] = useState("");
  const [selectedFlowId, setSelectedFlowId] = useState<number | "">("");
  const [selectedWorkKey, setSelectedWorkKey] = useState("");
  const [manualModel, setManualModel] = useState<ManualModelIdentityValue>({ enabled: false, modelNo: "", variantNo: "" });
  const [kroyNo, setKroyNo] = useState("");
  const [sewnQty, setSewnQty] = useState<NumberInputValue>("");
  const [sectionEntries, setSectionEntries] = useState<SectionEntry[]>(emptySectionEntries);
  const [defectiveQty, setDefectiveQty] = useState<NumberInputValue>("");
  const [defectReason, setDefectReason] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const { data: flows } = useSWR<Flow[]>("/api/sewing-flows", fetcher, { refreshInterval: 30_000 });
  const activeFlows = useMemo(() => (flows || []).filter((flow) => flow.is_active), [flows]);
  const selectedFlow = useMemo(
    () => activeFlows.find((flow) => flow.id === selectedFlowId) || null,
    [activeFlows, selectedFlowId],
  );
  const usesSectionEntry = Boolean(selectedFlow && SECTIONED_LINE_CODES.has(selectedFlow.code));
  const sectionTotal = sectionEntries.reduce(
    (total, entry) => total + (
      entry.isTwoPart
        ? numberOrZero(entry.topQty) + numberOrZero(entry.bottomQty)
        : numberOrZero(entry.sewnQty)
    ),
    0,
  );
  const sectionDefectiveTotal = sectionEntries.reduce((total, entry) => total + numberOrZero(entry.defectiveQty), 0);

  useEffect(() => {
    if (selectedFlowId === "" && activeFlows.length > 0) setSelectedFlowId(activeFlows[0].id);
  }, [activeFlows, selectedFlowId]);

  const lineContextUrl = selectedFlowId === "" ? null : `/api/sewing-daily-reports/line-context?sewing_flow_id=${selectedFlowId}`;
  const { data: lineContext, mutate: mutateLineContext, isLoading: loadingLine } = useSWR<LineContext>(
    lineContextUrl,
    fetcher,
    { refreshInterval: 15_000 },
  );
  const reportUrl = `/api/sewing-daily-reports?report_date=${encodeURIComponent(reportDate)}`;
  const { data: report, mutate: mutateReport, isLoading: loadingReport } = useSWR<ReportList>(
    reportUrl,
    fetcher,
    { refreshInterval: 20_000 },
  );

  useEffect(() => {
    const activeWork = lineContext?.active_work_orders || [];
    if (activeWork.length === 0) {
      setSelectedWorkKey("");
      if (usesSectionEntry) {
        setSectionEntries((current) => current.map((entry) => ({
          ...entry,
          workKey: "",
          manualModel: { ...entry.manualModel, enabled: true },
        })));
      } else {
        setManualModel((current) => ({ ...current, enabled: true }));
      }
      return;
    }
    if (usesSectionEntry) {
      setSelectedWorkKey("");
      setSectionEntries((current) => current.map((entry) => (
        activeWork.some((work) => sewingWorkKey(work) === entry.workKey)
          ? entry
          : { ...entry, workKey: sewingWorkKey(activeWork[0]), kroyNo: activeWork[0].kroy_no || "" }
      )));
      return;
    }
    if (!activeWork.some((work) => sewingWorkKey(work) === selectedWorkKey)) {
      setSelectedWorkKey(sewingWorkKey(activeWork[0]));
      setKroyNo(activeWork[0].kroy_no || "");
    }
  }, [lineContext, selectedWorkKey, usesSectionEntry]);

  const selectedWork = useMemo(
    () => (lineContext?.active_work_orders || []).find((work) => sewingWorkKey(work) === selectedWorkKey) || null,
    [lineContext, selectedWorkKey],
  );

  async function refresh() {
    setError("");
    setMessage("");
    await Promise.all([mutateLineContext(), mutateReport()]);
  }

  async function downloadReport(format: "xlsx" | "pdf") {
    setExportError("");
    if (!exportFromDate || !exportToDate || exportFromDate > exportToDate) {
      setExportError(t("page.sewingDailyReport.invalidExportRange"));
      return;
    }
    setDownloadingReport(format);
    try {
      const params = new URLSearchParams({
        from_date: exportFromDate,
        to_date: exportToDate,
        lang,
      });
      const response = await fetch(`/api/sewing-daily-reports/export.${format}?${params.toString()}`, {
        credentials: "same-origin",
      });
      if (!response.ok) {
        let detail = response.statusText;
        try {
          const body = await response.json();
          detail = body.detail || detail;
        } catch {}
        throw new Error(`${response.status}: ${detail}`);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
        || `daily_sewing_report_${exportFromDate}_${exportToDate}.${format}`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (downloadError: any) {
      setExportError(downloadError?.message || t("page.sewingDailyReport.reportDownloadFailed"));
    } finally {
      setDownloadingReport(null);
    }
  }

  async function saveReport() {
    setMessage("");
    setError("");
    if (selectedFlowId === "") {
      setError(t("page.sewingDailyReport.selectLine"));
      return;
    }
    const payloads: Record<string, unknown>[] = [];
    if (usesSectionEntry) {
      const activeWork = lineContext?.active_work_orders || [];
      for (const [index, entry] of sectionEntries.entries()) {
        const top = entry.isTwoPart ? numberOrZero(entry.topQty) : null;
        const bottom = entry.isTwoPart ? numberOrZero(entry.bottomQty) : null;
        const sewn = entry.isTwoPart ? (top || 0) + (bottom || 0) : numberOrZero(entry.sewnQty);
        const defective = numberOrZero(entry.defectiveQty);
        if (sewn <= 0) {
          if (defective > 0) {
            setError(t("page.sewingDailyReport.defectiveRange"));
            return;
          }
          continue;
        }
        const work = activeWork.find((candidate) => sewingWorkKey(candidate) === entry.workKey);
        if (!work && !entry.manualModel.modelNo.trim()) {
          setError(t("page.sewingDailyReport.manualModelRequired"));
          return;
        }
        if (defective < 0 || defective > sewn) {
          setError(t("page.sewingDailyReport.defectiveRange"));
          return;
        }
        payloads.push({
          report_date: reportDate,
          sewing_flow_id: selectedFlowId,
          work_order_id: work?.work_order_id ?? null,
          sewing_assignment_id: work?.sewing_assignment_id ?? null,
          manual_model_no: entry.manualModel.enabled || !work ? entry.manualModel.modelNo.trim() || null : null,
          manual_variant_no: entry.manualModel.enabled || !work ? entry.manualModel.variantNo.trim() || null : null,
          kroy_no: entry.kroyNo.trim() || null,
          section_no: index + 1,
          top_qty: top,
          bottom_qty: bottom,
          sewn_qty: sewn,
          defective_qty: defective,
          defect_reason: defective > 0 ? defectReason.trim() || null : null,
          notes: notes.trim() || null,
        });
      }
      if (payloads.length === 0) {
        setError(t("page.sewingDailyReport.sewnRequired"));
        return;
      }
      if (sectionDefectiveTotal > 0 && !defectReason.trim()) {
        setError(t("page.sewingDailyReport.reasonRequired"));
        return;
      }
    } else {
      const sewn = numberOrZero(sewnQty);
      const defective = numberOrZero(defectiveQty);
      if (!selectedWork && !manualModel.modelNo.trim()) {
        setError(t("page.sewingDailyReport.manualModelRequired"));
        return;
      }
      if (sewn <= 0) {
        setError(t("page.sewingDailyReport.sewnRequired"));
        return;
      }
      if (defective < 0 || defective > sewn) {
        setError(t("page.sewingDailyReport.defectiveRange"));
        return;
      }
      if (defective > 0 && !defectReason.trim()) {
        setError(t("page.sewingDailyReport.reasonRequired"));
        return;
      }
      payloads.push({
        report_date: reportDate,
        sewing_flow_id: selectedFlowId,
        work_order_id: selectedWork?.work_order_id ?? null,
        sewing_assignment_id: selectedWork?.sewing_assignment_id ?? null,
        manual_model_no: manualModel.enabled || !selectedWork ? manualModel.modelNo.trim() || null : null,
        manual_variant_no: manualModel.enabled || !selectedWork ? manualModel.variantNo.trim() || null : null,
        kroy_no: kroyNo.trim() || null,
        sewn_qty: sewn,
        defective_qty: defective,
        defect_reason: defectReason.trim() || null,
        notes: notes.trim() || null,
      });
    }
    setSaving(true);
    try {
      await Promise.all(payloads.map((payload) => api.post("/api/sewing-daily-reports", payload)));
      setSewnQty("");
      setSectionEntries((current) => current.map((entry) => ({
        ...entry,
        sewnQty: "",
        topQty: "",
        bottomQty: "",
        defectiveQty: "",
      })));
      setDefectiveQty("");
      setDefectReason("");
      setNotes("");
      setMessage(t("page.sewingDailyReport.saved"));
      await Promise.all([mutateReport(), mutateLineContext()]);
    } catch (err: any) {
      setError(err?.message || t("page.sewingDailyReport.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.sewingDailyReport.title")} subtitle={t("page.sewingDailyReport.subtitle")} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <section className="card p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-[#14110b]">{t("page.sewingDailyReport.entryTitle")}</h2>
              <p className="mt-1 text-sm text-[#56503f]">{t("page.sewingDailyReport.entryHint")}</p>
            </div>
            <Shirt className="h-5 w-5 shrink-0 text-[#8a8472]" />
          </div>

          <div className="space-y-3">
            <div>
              <label className="label" htmlFor="daily-sewing-date">{t("field.date")}</label>
              <div className="flex gap-2">
                <input
                  id="daily-sewing-date"
                  className="input"
                  type="date"
                  value={reportDate}
                  onChange={(event) => setReportDate(event.target.value || todayInputDate())}
                />
                <button type="button" className="icon-btn h-10 w-10 shrink-0" onClick={refresh} aria-label={t("btn.refresh")}>
                  <RefreshCw />
                </button>
              </div>
            </div>

            <div>
              <label className="label" htmlFor="daily-sewing-line">{t("field.line")}</label>
              <select
                id="daily-sewing-line"
                className="input"
                value={selectedFlowId}
                onChange={(event) => {
                  setSelectedFlowId(Number(event.target.value || 0) || "");
                  setSelectedWorkKey("");
                  setManualModel({ enabled: false, modelNo: "", variantNo: "" });
                  setKroyNo("");
                  setSewnQty("");
                  setSectionEntries(emptySectionEntries());
                  setError("");
                  setMessage("");
                }}
              >
                {activeFlows.map((flow) => (
                  <option key={flow.id} value={flow.id}>
                    {flow.name} ({flow.code})
                  </option>
                ))}
              </select>
            </div>

            {!usesSectionEntry && <div className="rounded-md border border-[#e3dfd3] bg-[#fbfaf6] p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-sm font-semibold text-[#14110b]">{t("page.sewingDailyReport.detectedOrder")}</div>
                {lineContext && <span className="badge">{lineContext.line_code}</span>}
              </div>
              {loadingLine && <div className="text-sm text-[#8a8472]">{t("common.loading")}</div>}
              {!loadingLine && (lineContext?.active_work_orders || []).length === 0 && (
                <div>
                  <div className="text-sm text-[#8a8472]">{t("page.sewingDailyReport.noActiveOrder")}</div>
                  <ManualModelIdentityFields
                    value={manualModel}
                    onChange={setManualModel}
                    inputIdPrefix="daily-sewing-manual-only"
                    alwaysVisible
                    modelNoRequired
                  />
                </div>
              )}
              {(lineContext?.active_work_orders || []).length > 0 && (
                <div className="space-y-2">
                  <SewingWorkPicker
                    options={lineContext!.active_work_orders}
                    value={selectedWorkKey}
                    onChange={(value) => {
                      setSelectedWorkKey(value);
                      setManualModel({ enabled: false, modelNo: "", variantNo: "" });
                      const work = lineContext!.active_work_orders.find((item) => sewingWorkKey(item) === value);
                      setKroyNo(work?.kroy_no || "");
                    }}
                  />
                  <ManualModelIdentityFields
                    value={manualModel}
                    onChange={setManualModel}
                    detectedModelNo={selectedWork?.model_no || selectedWork?.model_code}
                    detectedVariantNo={selectedWork?.variant_no}
                    inputIdPrefix="daily-sewing-manual"
                  />
                  {selectedWork && (
                    <div className="space-y-2">
                      {workBatchLabel(selectedWork) && (
                        <div className="text-xs text-[#56503f]">
                          {t("field.batch")}: <span className="font-medium text-[#14110b]">{workBatchLabel(selectedWork)}</span>
                        </div>
                      )}
                      <div className="grid grid-cols-3 gap-2 text-xs text-[#56503f]">
                        <div>
                          <div className="text-[#8a8472]">{t("page.sewingDailyReport.planned")}</div>
                          <div className="font-medium tabular-nums text-[#14110b]">{selectedWork.planned_qty}</div>
                        </div>
                        <div>
                          <div className="text-[#8a8472]">{t("page.sewingDailyReport.done")}</div>
                          <div className="font-medium tabular-nums text-[#14110b]">{selectedWork.completed_qty}</div>
                        </div>
                        <div>
                          <div className="text-[#8a8472]">{t("field.remaining")}</div>
                          <div className="font-medium tabular-nums text-[#14110b]">{selectedWork.remaining_qty}</div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {!loadingLine && (
                <div className="mt-2">
                  <label className="mb-1 block text-xs text-[#56503f]" htmlFor="daily-sewing-kroy-no">
                    {t("field.kroyNo")}
                  </label>
                  <input
                    id="daily-sewing-kroy-no"
                    className="input"
                    value={kroyNo}
                    maxLength={64}
                    onChange={(event) => setKroyNo(event.target.value)}
                  />
                </div>
              )}
            </div>}

            {usesSectionEntry && (
              <div className="space-y-3">
                {loadingLine && <div className="text-sm text-[#8a8472]">{t("common.loading")}</div>}
                {!loadingLine && (lineContext?.active_work_orders || []).length === 0 && (
                  <div className="rounded-md border border-[#e3dfd3] bg-[#fbfaf6] p-3 text-sm text-[#8a8472]">
                    {t("page.sewingDailyReport.noActiveOrder")}
                  </div>
                )}
                {!loadingLine && sectionEntries.map((entry, index) => {
                  const sectionWork = (lineContext?.active_work_orders || []).find((work) => sewingWorkKey(work) === entry.workKey);
                  return (
                  <div key={entry.id} className="rounded-md border border-[#e3dfd3] bg-[#fbfaf6] p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="text-sm font-semibold text-[#14110b]">{t("field.section")} {index + 1}</div>
                      {index >= 3 && (
                        <button
                          type="button"
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#e3dfd3] bg-white text-[#77705f] transition-colors hover:border-red-200 hover:text-red-600"
                          aria-label={t("page.sewingDailyReport.removeSection")}
                          title={t("page.sewingDailyReport.removeSection")}
                          onClick={() => setSectionEntries((current) => current.filter((item) => item.id !== entry.id))}
                        >
                          <Trash2 size={15} />
                        </button>
                      )}
                    </div>
                    {(lineContext?.active_work_orders || []).length > 0 && (
                      <SewingWorkPicker
                        options={lineContext!.active_work_orders}
                        value={entry.workKey}
                        onChange={(value) => {
                          const selected = lineContext!.active_work_orders.find((work) => sewingWorkKey(work) === value);
                          setSectionEntries((current) => current.map((item) => (
                            item.id === entry.id
                              ? {
                                  ...item,
                                  workKey: value,
                                  manualModel: { enabled: false, modelNo: "", variantNo: "" },
                                  kroyNo: selected?.kroy_no || "",
                                }
                              : item
                          )));
                        }}
                      />
                    )}
                    <ManualModelIdentityFields
                      value={entry.manualModel}
                      onChange={(manualValue) => {
                        setSectionEntries((current) => current.map((item) => (
                          item.id === entry.id ? { ...item, manualModel: manualValue } : item
                        )));
                      }}
                      detectedModelNo={sectionWork?.model_no || sectionWork?.model_code}
                      detectedVariantNo={sectionWork?.variant_no}
                      inputIdPrefix={`daily-sewing-section-${index + 1}-manual`}
                      alwaysVisible={!sectionWork}
                      modelNoRequired={!sectionWork}
                    />
                    <div className="mt-2">
                      <label className="mb-1 block text-xs text-[#56503f]" htmlFor={`daily-sewing-section-kroy-${index + 1}`}>
                        {t("field.kroyNo")}
                      </label>
                      <input
                        id={`daily-sewing-section-kroy-${index + 1}`}
                        className="input"
                        value={entry.kroyNo}
                        maxLength={64}
                        onChange={(event) => {
                          const value = event.target.value;
                          setSectionEntries((current) => current.map((item) => (
                            item.id === entry.id ? { ...item, kroyNo: value } : item
                          )));
                        }}
                      />
                    </div>
                    <label className="mt-3 flex cursor-pointer items-center gap-2 rounded-md border border-[#e3dfd3] bg-white px-3 py-2 text-sm text-[#3e392f]">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-[#14110b]"
                        checked={entry.isTwoPart}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setSectionEntries((current) => current.map((item) => (
                            item.id === entry.id
                              ? {
                                  ...item,
                                  isTwoPart: checked,
                                  sewnQty: "",
                                  topQty: "",
                                  bottomQty: "",
                                }
                              : item
                          )));
                        }}
                      />
                      <span className="font-medium">{t("page.sewingDailyReport.twoPartGarment")}</span>
                    </label>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {entry.isTwoPart ? (
                        <>
                          <div>
                            <label className="mb-1 block text-xs text-[#56503f]" htmlFor={`daily-sewing-section-top-${entry.id}`}>
                              {t("page.sewingDailyReport.topQty")}
                            </label>
                            <input
                              id={`daily-sewing-section-top-${entry.id}`}
                              className="input"
                              type="number"
                              min={0}
                              value={entry.topQty}
                              onChange={(event) => {
                                const value = parseNumberInput(event.target.value);
                                setSectionEntries((current) => current.map((item) => (
                                  item.id === entry.id ? { ...item, topQty: value } : item
                                )));
                              }}
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-xs text-[#56503f]" htmlFor={`daily-sewing-section-bottom-${entry.id}`}>
                              {t("page.sewingDailyReport.bottomQty")}
                            </label>
                            <input
                              id={`daily-sewing-section-bottom-${entry.id}`}
                              className="input"
                              type="number"
                              min={0}
                              value={entry.bottomQty}
                              onChange={(event) => {
                                const value = parseNumberInput(event.target.value);
                                setSectionEntries((current) => current.map((item) => (
                                  item.id === entry.id ? { ...item, bottomQty: value } : item
                                )));
                              }}
                            />
                          </div>
                        </>
                      ) : (
                        <div>
                          <label className="mb-1 block text-xs text-[#56503f]" htmlFor={`daily-sewing-section-${entry.id}`}>
                            {t("page.sewingDailyReport.sewnQty")}
                          </label>
                          <input
                            id={`daily-sewing-section-${entry.id}`}
                            className="input"
                            type="number"
                            min={0}
                            value={entry.sewnQty}
                            onChange={(event) => {
                              const value = parseNumberInput(event.target.value);
                              setSectionEntries((current) => current.map((item) => (
                                item.id === entry.id ? { ...item, sewnQty: value } : item
                              )));
                            }}
                          />
                        </div>
                      )}
                      <div className={entry.isTwoPart ? "col-span-2" : ""}>
                        <label className="mb-1 block text-xs text-[#56503f]" htmlFor={`daily-sewing-section-defective-${entry.id}`}>
                          {t("page.sewingDailyReport.defectiveQty")}
                        </label>
                        <input
                          id={`daily-sewing-section-defective-${entry.id}`}
                          className="input"
                          type="number"
                          min={0}
                          value={entry.defectiveQty}
                          onChange={(event) => {
                            const value = parseNumberInput(event.target.value);
                            setSectionEntries((current) => current.map((item) => (
                              item.id === entry.id ? { ...item, defectiveQty: value } : item
                            )));
                          }}
                        />
                      </div>
                    </div>
                  </div>
                  );
                })}
                {!loadingLine && sectionEntries.length < MAX_SECTION_COUNT && (
                  <button
                    type="button"
                    className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-[#cfc8b8] bg-white px-3 py-2 text-sm font-medium text-[#3e392f] transition-colors hover:border-[#8c836f] hover:bg-[#f8f6f0]"
                    onClick={() => {
                      const activeWork = lineContext?.active_work_orders?.[0];
                      setSectionEntries((current) => [
                        ...current,
                        {
                          ...createSectionEntry(),
                          workKey: activeWork ? sewingWorkKey(activeWork) : "",
                          kroyNo: activeWork?.kroy_no || "",
                          manualModel: activeWork
                            ? { enabled: false, modelNo: "", variantNo: "" }
                            : { enabled: true, modelNo: "", variantNo: "" },
                        },
                      ]);
                    }}
                  >
                    <Plus size={16} />
                    {t("page.sewingDailyReport.addSection")}
                  </button>
                )}
                {!loadingLine && (
                  <div className="flex items-center justify-between border-t border-[#e3dfd3] pt-2 text-sm">
                    <span className="text-[#56503f]">{t("page.sewingDailyReport.totalSewn")}</span>
                    <span className="font-semibold tabular-nums text-[#14110b]">{sectionTotal}</span>
                  </div>
                )}
              </div>
            )}

            {!usesSectionEntry && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="daily-sewing-sewn">{t("page.sewingDailyReport.sewnQty")}</label>
                  <input
                    id="daily-sewing-sewn"
                    className="input"
                    type="number"
                    min={0}
                    value={sewnQty}
                    onChange={(event) => setSewnQty(parseNumberInput(event.target.value))}
                  />
                </div>
                <div>
                <label className="label" htmlFor="daily-sewing-defective">{t("page.sewingDailyReport.defectiveQty")}</label>
                <input
                  id="daily-sewing-defective"
                  className="input"
                  type="number"
                  min={0}
                  value={defectiveQty}
                  onChange={(event) => setDefectiveQty(parseNumberInput(event.target.value))}
                />
                </div>
              </div>
            )}

            <div>
              <label className="label" htmlFor="daily-sewing-reason">{t("field.defectReason")}</label>
              <DefectReasonSelect
                id="daily-sewing-reason"
                value={defectReason}
                onChange={setDefectReason}
                required={(usesSectionEntry ? sectionDefectiveTotal : numberOrZero(defectiveQty)) > 0}
              />
            </div>

            <div>
              <label className="label" htmlFor="daily-sewing-notes">{t("field.notes")}</label>
              <textarea
                id="daily-sewing-notes"
                className="input min-h-[82px] resize-y"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </div>

            {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
            {message && <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">{message}</div>}

            <button
              type="button"
              className="btn btn-primary h-10 w-full"
              onClick={saveReport}
              disabled={saving || selectedFlowId === "" || loadingLine}
            >
              <Save />
              {saving ? t("common.saving") : t("page.sewingDailyReport.save")}
            </button>
          </div>
        </section>

        <div className="space-y-4">
          <section className="card p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <CalendarDays className="h-5 w-5 text-[#8a8472]" />
                <h2 className="text-base font-semibold text-[#14110b]">{t("page.sewingDailyReport.reportTitle")}</h2>
              </div>
              <button type="button" className="btn" onClick={refresh}>
                <RefreshCw />
                {t("btn.refresh")}
              </button>
            </div>

            <div className="mb-4 border-y border-[#e3dfd3] py-3">
              <div className="mb-3">
                <h3 className="text-sm font-semibold text-[#14110b]">{t("page.sewingDailyReport.exportTitle")}</h3>
                <p className="mt-1 text-xs text-[#6f6858]">{t("page.sewingDailyReport.exportHint")}</p>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-[minmax(150px,1fr)_minmax(150px,1fr)_auto_auto] lg:items-end">
                <div>
                  <label className="label" htmlFor="daily-sewing-export-from">
                    {t("page.sewingDailyReport.fromDate")}
                  </label>
                  <input
                    id="daily-sewing-export-from"
                    className="input"
                    type="date"
                    value={exportFromDate}
                    onChange={(event) => setExportFromDate(event.target.value)}
                  />
                </div>
                <div>
                  <label className="label" htmlFor="daily-sewing-export-to">
                    {t("page.sewingDailyReport.toDate")}
                  </label>
                  <input
                    id="daily-sewing-export-to"
                    className="input"
                    type="date"
                    value={exportToDate}
                    onChange={(event) => setExportToDate(event.target.value)}
                  />
                </div>
                <button
                  type="button"
                  className="btn h-10"
                  disabled={Boolean(downloadingReport)}
                  onClick={() => void downloadReport("xlsx")}
                >
                  <FileSpreadsheet />
                  {downloadingReport === "xlsx"
                    ? t("common.loading")
                    : t("page.sewingDailyReport.excelReport")}
                </button>
                <button
                  type="button"
                  className="btn h-10"
                  disabled={Boolean(downloadingReport)}
                  onClick={() => void downloadReport("pdf")}
                >
                  <FileText />
                  {downloadingReport === "pdf"
                    ? t("common.loading")
                    : t("page.sewingDailyReport.pdfReport")}
                </button>
              </div>
              {exportError && (
                <div className="mt-2 text-sm text-red-700" role="alert">
                  {exportError}
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-md border border-[#e3dfd3] p-3">
                <div className="text-xs text-[#8a8472]">{t("page.sewingDailyReport.totalSewn")}</div>
                <div className="mt-1 text-xl font-semibold tabular-nums text-[#14110b]">{report?.total_sewn_qty || 0}</div>
              </div>
              <div className="rounded-md border border-[#e3dfd3] p-3">
                <div className="text-xs text-[#8a8472]">{t("page.sewingDailyReport.totalDefective")}</div>
                <div className="mt-1 text-xl font-semibold tabular-nums text-[#14110b]">{report?.total_defective_qty || 0}</div>
              </div>
              <div className="rounded-md border border-[#e3dfd3] p-3">
                <div className="text-xs text-[#8a8472]">{t("page.sewingDailyReport.linesReported")}</div>
                <div className="mt-1 text-xl font-semibold tabular-nums text-[#14110b]">{report?.summary.length || 0}</div>
              </div>
            </div>

            <div className="mt-4 overflow-x-auto rounded-md border border-[#e3dfd3]">
              <table className="table min-w-[720px]">
                <thead>
                  <tr>
                    <th>{t("field.line")}</th>
                    <th className="text-right">{t("page.sewingDailyReport.sewnQty")}</th>
                    <th className="text-right">{t("page.sewingDailyReport.defectiveQty")}</th>
                    <th>{t("common.model")} / {t("field.variantNo")}</th>
                    <th>{t("field.kroyNo")}</th>
                    <th>{t("field.reason")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(report?.summary || []).map((line) => (
                    <tr key={line.sewing_flow_id}>
                      <td>
                        <div className="font-medium text-[#14110b]">{line.line_name}</div>
                        <div className="text-xs text-[#8a8472]">{line.line_code}</div>
                      </td>
                      <td className="text-right tabular-nums">{line.total_sewn_qty}</td>
                      <td className="text-right tabular-nums">
                        <div>{line.total_defective_qty}</div>
                        <div className="text-xs text-[#8a8472]">{defectRate(line.total_sewn_qty, line.total_defective_qty)}</div>
                      </td>
                      <td>
                        <div className="space-y-2">
                          {(line.models || []).map((model, index) => (
                            <SewingModelCell key={model.model_id || `${model.model_code}-${index}`} model={model} />
                          ))}
                          {!(line.models || []).length && "-"}
                        </div>
                      </td>
                      <td>{line.kroy_nos.length ? line.kroy_nos.join(", ") : "-"}</td>
                      <td>{line.defect_reasons.length ? line.defect_reasons.map((reason) => defectReasonLabel(reason, t)).join(", ") : "-"}</td>
                    </tr>
                  ))}
                  {!loadingReport && (report?.summary || []).length === 0 && (
                    <tr><td colSpan={6} className="text-sm text-[#8a8472]">{t("page.sewingDailyReport.noReports")}</td></tr>
                  )}
                  {loadingReport && <tr><td colSpan={6} className="text-sm text-[#8a8472]">{t("common.loading")}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-[#e3dfd3] px-4 py-3">
              <ClipboardList className="h-5 w-5 text-[#8a8472]" />
              <h2 className="text-base font-semibold text-[#14110b]">{t("page.sewingDailyReport.entriesTitle")}</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="table min-w-[860px]">
                <thead>
                  <tr>
                    <th>{t("field.when")}</th>
                    <th>{t("field.line")}</th>
                    <th>{t("common.model")} / {t("field.variantNo")}</th>
                    <th>{t("field.kroyNo")}</th>
                    <th className="text-right">{t("page.sewingDailyReport.sewnQty")}</th>
                    <th className="text-right">{t("page.sewingDailyReport.defectiveQty")}</th>
                    <th>{t("field.defectReason")}</th>
                    <th>{t("field.notes")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(report?.rows || []).map((row) => (
                    <tr key={row.id}>
                      <td>{formatDateTime(row.created_at)}</td>
                      <td>
                        <div className="font-medium text-[#14110b]">{row.line_name}</div>
                        <div className="text-xs text-[#8a8472]">
                          {row.line_code}{row.section_no ? ` · ${t("field.section")} ${row.section_no}` : ""}
                        </div>
                      </td>
                      <td><SewingModelCell model={row} /></td>
                      <td>{row.kroy_no || "-"}</td>
                      <td className="text-right tabular-nums">
                        <div>{row.sewn_qty}</div>
                        {row.top_qty !== null && row.bottom_qty !== null && (
                          <div className="mt-1 whitespace-nowrap text-xs text-[#8a8472]">
                            {t("page.sewingDailyReport.topQty")}: {row.top_qty} · {t("page.sewingDailyReport.bottomQty")}: {row.bottom_qty}
                          </div>
                        )}
                        {row.section_quantities?.length === 3 && (
                          <div className="mt-1 whitespace-nowrap text-xs text-[#8a8472]">
                            {row.section_quantities.map((quantity, index) => `${t("field.section")} ${index + 1}: ${quantity}`).join(" · ")}
                          </div>
                        )}
                      </td>
                      <td className="text-right tabular-nums">{row.defective_qty}</td>
                      <td>{defectReasonLabel(row.defect_reason, t)}</td>
                      <td className="max-w-[260px] truncate" title={row.notes || ""}>{row.notes || "-"}</td>
                    </tr>
                  ))}
                  {!loadingReport && (report?.rows || []).length === 0 && (
                    <tr><td colSpan={8} className="text-sm text-[#8a8472]">{t("page.sewingDailyReport.noReports")}</td></tr>
                  )}
                  {loadingReport && <tr><td colSpan={8} className="text-sm text-[#8a8472]">{t("common.loading")}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
