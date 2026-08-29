"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Download, Filter, Printer, RotateCcw } from "lucide-react";

import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import SearchableSelect from "@/components/SearchableSelect";
import SewingProductionReportTable from "@/components/payroll/SewingProductionReportTable";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import {
  buildSewingReportParams,
  type ReportOption,
  type SewingProductionReportFilters,
  type SewingProductionReportOptions,
  type SewingProductionReportResponse,
  type SewingProductionReportRow,
} from "@/lib/sewingProductionReport";

const PAGE_SIZE = 100;

function localDateTime(date: Date, endOfDay = false): string {
  const local = new Date(date);
  if (endOfDay) local.setHours(23, 59, 59, 0);
  else local.setHours(0, 0, 0, 0);
  const offset = local.getTimezoneOffset() * 60_000;
  return new Date(local.getTime() - offset).toISOString().slice(0, 19);
}

function initialFilters(): SewingProductionReportFilters {
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  return {
    dateFrom: localDateTime(monthStart),
    dateTo: localDateTime(now, true),
    employeeId: "",
    orderNo: "",
    cuttingReference: "",
    modelCode: "",
    sewingLine: "",
    operation: "",
    barcode: "",
    size: "",
    factoryCode: "",
    status: "active",
  };
}

function ReportFilterSelect({
  id,
  label,
  value,
  options,
  allLabel,
  searchPlaceholder,
  noResultsText,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: ReportOption[];
  allLabel: string;
  searchPlaceholder: string;
  noResultsText: string;
  onChange: (value: string) => void;
}) {
  const searchableOptions = useMemo(
    () => [{ value: "", label: allLabel }, ...options],
    [allLabel, options],
  );

  return (
    <div className="min-w-0">
      <label className="label" htmlFor={id}>{label}</label>
      <SearchableSelect<string>
        inputId={id}
        value={value}
        options={searchableOptions}
        placeholder={searchPlaceholder}
        noResultsText={noResultsText}
        onChange={(nextValue) => onChange(nextValue)}
      />
    </div>
  );
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function SewingProductionReportPage() {
  const { t, lang } = useT();
  const [draft, setDraft] = useState<SewingProductionReportFilters>(initialFilters);
  const [applied, setApplied] = useState<SewingProductionReportFilters>(initialFilters);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [action, setAction] = useState<"xlsx" | "print" | null>(null);
  const [actionError, setActionError] = useState("");
  const [printRows, setPrintRows] = useState<SewingProductionReportRow[] | null>(null);

  const query = useMemo(
    () => buildSewingReportParams(applied, page, pageSize).toString(),
    [applied, page, pageSize],
  );
  const { data, error, isLoading } = useSWR<SewingProductionReportResponse>(
    `/api/payroll/reports/sewing-production?${query}`,
    fetcher,
  );
  const optionQuery = draft.factoryCode
    ? `?factory_code=${encodeURIComponent(draft.factoryCode)}`
    : "";
  const { data: scopedOptions } = useSWR<SewingProductionReportOptions>(
    `/api/payroll/reports/sewing-production/options${optionQuery}`,
    fetcher,
  );

  const reportRows = printRows || data?.items || [];
  const rowOffset = printRows ? 0 : (page - 1) * pageSize;
  const options = scopedOptions;
  const printSummary = {
    qrCount: printRows ? reportRows.length : Number(data?.total || 0),
    totalQuantity: printRows
      ? reportRows.reduce((sum, row) => sum + Number(row.quantity || 0), 0)
      : Number(data?.total_quantity || 0),
    totalRate: reportRows.reduce((sum, row) => sum + Number(row.rate_per_piece || 0), 0),
    totalAmount: printRows
      ? reportRows.reduce((sum, row) => sum + Number(row.total_amount || 0), 0)
      : Number(data?.total_amount || 0),
  };

  function update<K extends keyof SewingProductionReportFilters>(key: K, value: SewingProductionReportFilters[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function updateFactory(factoryCode: string) {
    setDraft((current) => ({
      ...current,
      factoryCode,
      employeeId: "",
      orderNo: "",
      cuttingReference: "",
      modelCode: "",
      sewingLine: "",
      operation: "",
      size: "",
    }));
  }

  function applyFilters(event: React.FormEvent) {
    event.preventDefault();
    setPage(1);
    setApplied({ ...draft });
  }

  function resetFilters() {
    const next = initialFilters();
    setDraft(next);
    setApplied(next);
    setPage(1);
  }

  async function fetchAllRows(): Promise<SewingProductionReportRow[]> {
    const rows: SewingProductionReportRow[] = [];
    let currentPage = 1;
    let total = 1;
    while (rows.length < total) {
      const params = buildSewingReportParams(applied, currentPage, 5000);
      const response = await api.get<SewingProductionReportResponse>(
        `/api/payroll/reports/sewing-production?${params.toString()}`,
        60_000,
      );
      total = response.total;
      rows.push(...response.items);
      if (!response.items.length) break;
      currentPage += 1;
    }
    return rows;
  }

  async function exportExcel() {
    setAction("xlsx");
    setActionError("");
    try {
      const params = buildSewingReportParams(applied, 1, 1);
      params.delete("limit");
      params.delete("offset");
      params.set("lang", lang);
      const response = await fetch(`/api/payroll/reports/sewing-production.xlsx?${params.toString()}`, {
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
      const disposition = response.headers.get("content-disposition") || "";
      const serverFilename = disposition.match(/filename="?([^";]+)"?/i)?.[1];
      const fallbackFilename = `sewing-production-report-${new Date().toISOString().slice(0, 10)}.xlsx`;
      downloadBlob(serverFilename || fallbackFilename, await response.blob());
    } catch (exportError: any) {
      setActionError(exportError?.message || t("page.sewingReport.exportFailed"));
    } finally {
      setAction(null);
    }
  }

  async function printReport() {
    setAction("print");
    setActionError("");
    try {
      const rows = await fetchAllRows();
      setPrintRows(rows);
      window.setTimeout(() => {
        window.print();
        setPrintRows(null);
      }, 100);
    } catch (printError: any) {
      setActionError(printError?.message || t("page.sewingReport.printFailed"));
    } finally {
      setAction(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="no-print">
        <PageHeader
          title={t("page.sewingReport.title")}
          subtitle={t("page.sewingReport.subtitle")}
          actions={(
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn" onClick={exportExcel} disabled={Boolean(action) || !data?.total}>
                <Download />
                <span>{action === "xlsx" ? t("page.sewingReport.exporting") : "Excel"}</span>
              </button>
              <button type="button" className="btn" onClick={printReport} disabled={Boolean(action) || !data?.total}>
                <Printer />
                <span>{action === "print" ? t("page.sewingReport.preparingPrint") : t("common.print")}</span>
              </button>
            </div>
          )}
        />
      </div>

      <form className="card p-4 no-print" onSubmit={applyFilters}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="app-card-title">{t("page.sewingReport.filters")}</h2>
            <p className="mt-1 text-xs text-[#8a8472]">{t("page.sewingReport.filterHint")}</p>
          </div>
          <Filter className="h-5 w-5 text-[#8a8472]" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <label>
            <span className="label">{t("page.sewingReport.dateFrom")}</span>
            <input className="input" type="datetime-local" step="1" value={draft.dateFrom} onChange={(e) => update("dateFrom", e.target.value)} />
          </label>
          <label>
            <span className="label">{t("page.sewingReport.dateTo")}</span>
            <input className="input" type="datetime-local" step="1" value={draft.dateTo} onChange={(e) => update("dateTo", e.target.value)} />
          </label>
          <ReportFilterSelect
            id="sewing-report-employee"
            label={t("page.sewingReport.employee")}
            value={draft.employeeId}
            options={options?.employees || []}
            allLabel={t("page.sewingReport.allEmployees")}
            searchPlaceholder={t("page.sewingReport.searchEmployee")}
            noResultsText={t("page.sewingReport.noFilterOptions")}
            onChange={(value) => update("employeeId", value)}
          />
          <label>
            <span className="label">{t("page.sewingReport.factory")}</span>
            <select className="input" value={draft.factoryCode} onChange={(e) => updateFactory(e.target.value)}>
              <option value="">{t("common.all")}</option>
              <option value="MIL">Milana</option>
              <option value="BST">Besttex</option>
              <option value="ECO">Eco Cotton</option>
            </select>
          </label>
          <ReportFilterSelect
            id="sewing-report-order"
            label={t("page.sewingReport.order")}
            value={draft.orderNo}
            options={options?.orders || []}
            allLabel={t("page.sewingReport.allOrders")}
            searchPlaceholder={t("page.sewingReport.searchOrder")}
            noResultsText={t("page.sewingReport.noFilterOptions")}
            onChange={(value) => update("orderNo", value)}
          />
          <ReportFilterSelect
            id="sewing-report-cutting"
            label={t("page.sewingReport.cutting")}
            value={draft.cuttingReference}
            options={options?.cutting_references || []}
            allLabel={t("page.sewingReport.allCutting")}
            searchPlaceholder={t("page.sewingReport.searchCutting")}
            noResultsText={t("page.sewingReport.noFilterOptions")}
            onChange={(value) => update("cuttingReference", value)}
          />
          <ReportFilterSelect
            id="sewing-report-model"
            label={t("page.sewingReport.model")}
            value={draft.modelCode}
            options={options?.models || []}
            allLabel={t("page.sewingReport.allModels")}
            searchPlaceholder={t("page.sewingReport.searchModel")}
            noResultsText={t("page.sewingReport.noFilterOptions")}
            onChange={(value) => update("modelCode", value)}
          />
          <ReportFilterSelect
            id="sewing-report-line"
            label={t("page.sewingReport.line")}
            value={draft.sewingLine}
            options={options?.sewing_lines || []}
            allLabel={t("page.sewingReport.allLines")}
            searchPlaceholder={t("page.sewingReport.searchLine")}
            noResultsText={t("page.sewingReport.noFilterOptions")}
            onChange={(value) => update("sewingLine", value)}
          />
          <ReportFilterSelect
            id="sewing-report-operation"
            label={t("page.sewingReport.operation")}
            value={draft.operation}
            options={options?.operations || []}
            allLabel={t("page.sewingReport.allOperations")}
            searchPlaceholder={t("page.sewingReport.searchOperation")}
            noResultsText={t("page.sewingReport.noFilterOptions")}
            onChange={(value) => update("operation", value)}
          />
          <label>
            <span className="label">{t("page.sewingReport.barcode")}</span>
            <input className="input font-mono" value={draft.barcode} onChange={(e) => update("barcode", e.target.value)} />
          </label>
          <ReportFilterSelect
            id="sewing-report-size"
            label={t("page.sewingReport.size")}
            value={draft.size}
            options={options?.sizes || []}
            allLabel={t("page.sewingReport.allSizes")}
            searchPlaceholder={t("page.sewingReport.searchSize")}
            noResultsText={t("page.sewingReport.noFilterOptions")}
            onChange={(value) => update("size", value)}
          />
          <label>
            <span className="label">{t("page.sewingReport.status")}</span>
            <select className="input" value={draft.status} onChange={(e) => update("status", e.target.value)}>
              <option value="active">{t("page.sewingReport.activeRecords")}</option>
              <option value="recorded">{t("page.sewingReport.recorded")}</option>
              <option value="approved">{t("page.sewingReport.approved")}</option>
              <option value="paid">{t("page.sewingReport.paid")}</option>
              <option value="voided">{t("page.sewingReport.voided")}</option>
              <option value="all">{t("common.all")}</option>
            </select>
          </label>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button type="button" className="btn" onClick={resetFilters}>
            <RotateCcw />
            <span>{t("page.sewingReport.reset")}</span>
          </button>
          <button type="submit" className="btn btn-primary">
            <Filter />
            <span>{t("page.sewingReport.apply")}</span>
          </button>
        </div>
      </form>

      {(error || actionError) && (
        <div className="card border-red-200 bg-red-50 p-3 text-sm text-red-700 no-print">
          {actionError || error?.message || t("page.sewingReport.loadFailed")}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3 no-print">
        <div className="kpi-card">
          <div className="label">{t("page.sewingReport.records")}</div>
          <div className="text-2xl font-semibold tabular-nums">{Number(data?.total || 0).toLocaleString(lang)}</div>
        </div>
        <div className="kpi-card">
          <div className="label">{t("page.sewingReport.totalQuantity")}</div>
          <div className="text-2xl font-semibold tabular-nums">{Number(data?.total_quantity || 0).toLocaleString(lang)}</div>
        </div>
        <div className="kpi-card">
          <div className="label">{t("page.sewingReport.totalAmount")}</div>
          <div className="text-2xl font-semibold tabular-nums">
            {Number(data?.total_amount || 0).toLocaleString(lang, { maximumFractionDigits: 2 })} {data?.currency || "UZS"}
          </div>
        </div>
      </div>

      <section className="card sewing-report-print-area">
        <div className="hidden border-b border-[#ded9ca] px-4 py-3 print:block">
          <h1 className="text-lg font-semibold">{t("page.sewingReport.title")}</h1>
          <p className="mt-1 text-xs text-[#56503f]">
            {new Date(applied.dateFrom).toLocaleString(lang)} — {new Date(applied.dateTo).toLocaleString(lang)}
          </p>
        </div>
        {isLoading && !printRows ? (
          <div className="p-8 text-center text-sm text-[#8a8472]">{t("common.loading")}</div>
        ) : (
          <SewingProductionReportTable rows={reportRows} rowOffset={rowOffset} lang={lang} t={t} />
        )}
        {!printRows && (
          <div className="no-print">
            <PaginationControls
              page={page}
              pageSize={pageSize}
              total={data?.total || 0}
              count={data?.items.length || 0}
              pageSizeOptions={[50, 100, 200, 500]}
              onPageChange={setPage}
              onPageSizeChange={(next) => {
                setPageSize(next);
                setPage(1);
              }}
            />
          </div>
        )}
        <div className="sewing-report-print-summary hidden border-t-2 border-[#14110b] px-4 py-3 print:block">
          <div className="mb-2 text-sm font-bold">{t("page.sewingReport.printTotals")}</div>
          <dl className="grid grid-cols-4 gap-5 tabular-nums">
            <div>
              <dt>{t("page.sewingReport.scannedQrCount")}</dt>
              <dd>{printSummary.qrCount.toLocaleString(lang)}</dd>
            </div>
            <div>
              <dt>{t("page.sewingReport.totalCompletedPieces")}</dt>
              <dd>{printSummary.totalQuantity.toLocaleString(lang)} {t("page.orderQr.pieces")}</dd>
            </div>
            <div>
              <dt>{t("page.sewingReport.totalRate")}</dt>
              <dd>{printSummary.totalRate.toLocaleString(lang, { maximumFractionDigits: 2 })} {data?.currency || "UZS"}</dd>
            </div>
            <div>
              <dt>{t("page.sewingReport.totalAmount")}</dt>
              <dd>{printSummary.totalAmount.toLocaleString(lang, { maximumFractionDigits: 2 })} {data?.currency || "UZS"}</dd>
            </div>
          </dl>
        </div>
      </section>

      <style jsx global>{`
        @media print {
          @page { size: landscape; margin: 8mm; }
          body * { visibility: hidden !important; }
          .sewing-report-print-area,
          .sewing-report-print-area * { visibility: visible !important; }
          .sewing-report-print-area {
            position: absolute !important;
            inset: 0 auto auto 0 !important;
            width: 100% !important;
            border: 0 !important;
            box-shadow: none !important;
          }
          .sewing-report-print-area .overflow-x-auto { overflow: visible !important; }
          .sewing-report-print-area table { min-width: 0 !important; width: 100% !important; font-size: 9.5px !important; font-weight: 700 !important; }
          .sewing-report-print-area th,
          .sewing-report-print-area td { padding: 4px !important; border: 1px solid #777 !important; color: #000 !important; }
          .sewing-report-print-area th { font-weight: 700 !important; background: #f0f0f0 !important; }
          .sewing-report-print-table { table-layout: fixed !important; }
          .sewing-report-print-summary { break-inside: avoid !important; page-break-inside: avoid !important; color: #000 !important; }
          .sewing-report-print-summary dt { font-size: 10px !important; font-weight: 600 !important; }
          .sewing-report-print-summary dd { margin-top: 2px !important; font-size: 14px !important; font-weight: 700 !important; }
          .no-print { display: none !important; }
        }
      `}</style>
    </div>
  );
}
