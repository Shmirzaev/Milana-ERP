"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import QRCode from "qrcode";
import { Printer, RefreshCw, RotateCcw, Search } from "lucide-react";

import PageHeader from "@/components/PageHeader";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type QrLabel = {
  id: number;
  label_uid: string;
  qr_token: string;
  payload?: string | null;
  production_no?: string | null;
  sales_order_no?: string | null;
  batch_no?: string | null;
  model_code?: string | null;
  operation_section?: string | null;
  operation_code?: string | null;
  operation_name?: string | null;
  sewing_flow_id?: number | null;
  sewing_line_code?: string | null;
  sewing_line_name?: string | null;
  cutting_passport_id?: number | null;
  cutting_passport_no?: string | null;
  size?: string | null;
  copy_index: number;
  quantity: number | string;
  rate_per_piece: number | string;
  currency: string;
  status: "available" | "scanned";
  payroll_record_id?: number | null;
  employee_id?: number | null;
  employee_name?: string | null;
  department_name?: string | null;
  payroll_status?: string | null;
  issued_at: string;
  last_scanned_at?: string | null;
  returned_at?: string | null;
  return_count: number;
};

type QrControlResponse = {
  items: QrLabel[];
  total: number;
  available_count: number;
  scanned_count: number;
};

type QrGroup = {
  orderNo: string;
  rows: QrLabel[];
  models: string[];
  batches: string[];
  scanned: number;
};

type PrintableLabel = QrLabel & { qrSrc: string };

const PAGE_SIZE = 100;

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatCompactDateTime(value?: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function numberText(value: number | string): string {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(value);
}

function orderNumber(row: QrLabel): string {
  return row.sales_order_no || row.production_no || "No order";
}

function uniqueText(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))];
}

export default function PayrollQrControlPage() {
  const { t } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"all" | "available" | "scanned">("all");
  const [page, setPage] = useState(0);
  const [returningId, setReturningId] = useState<number | null>(null);
  const [printingOrder, setPrintingOrder] = useState<string | null>(null);
  const [printRows, setPrintRows] = useState<PrintableLabel[]>([]);
  const [message, setMessage] = useState("");
  const [actionError, setActionError] = useState("");

  useEffect(() => setPage(0), [search, status]);

  useEffect(() => {
    const finishPrint = () => {
      document.body.classList.remove("payroll-qr-reprint-active");
      setPrintRows([]);
    };
    window.addEventListener("afterprint", finishPrint);
    return () => {
      window.removeEventListener("afterprint", finishPrint);
      document.body.classList.remove("payroll-qr-reprint-active");
    };
  }, []);

  const endpoint = useMemo(() => {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    });
    if (search.trim()) params.set("search", search.trim());
    if (status !== "all") params.set("status", status);
    return `/api/payroll/qr-labels?${params.toString()}`;
  }, [page, search, status]);

  const { data, error, isLoading, mutate } = useSWR<QrControlResponse>(endpoint, fetcher, {
    refreshInterval: 15_000,
  });
  const rows = useMemo(() => data?.items || [], [data?.items]);
  const groups = useMemo<QrGroup[]>(() => {
    const grouped = new Map<string, QrLabel[]>();
    rows.forEach((row) => {
      const key = orderNumber(row);
      grouped.set(key, [...(grouped.get(key) || []), row]);
    });
    return [...grouped.entries()].map(([groupOrderNo, groupRows]) => ({
      orderNo: groupOrderNo,
      rows: groupRows,
      models: uniqueText(groupRows.map((row) => row.model_code)),
      batches: uniqueText(groupRows.map((row) => row.batch_no)),
      scanned: groupRows.filter((row) => row.status === "scanned").length,
    }));
  }, [rows]);
  const canReturn = can(me, "payroll.manage");
  const from = data?.total ? page * PAGE_SIZE + 1 : 0;
  const to = Math.min((page + 1) * PAGE_SIZE, data?.total || 0);

  async function returnLabel(row: QrLabel) {
    const confirmed = await dialogs.ask({
      title: t("page.payrollQrControl.returnTitle"),
      message: t("page.payrollQrControl.returnConfirm", {
        qr: row.qr_token || row.label_uid,
        employee: row.employee_name || t("page.payrollQrControl.unknownEmployee"),
      }),
      confirmText: t("page.payrollQrControl.returnQr"),
      tone: "danger",
    });
    if (!confirmed) return;
    setReturningId(row.id);
    setMessage("");
    setActionError("");
    try {
      await api.post(`/api/payroll/qr-labels/${row.id}/return`);
      setMessage(t("page.payrollQrControl.returned"));
      await mutate();
    } catch (err: any) {
      setActionError(err?.message || t("page.payrollQrControl.returnFailed"));
    } finally {
      setReturningId(null);
    }
  }

  async function reprintOrder(orderNo: string) {
    if (printingOrder) return;
    setPrintingOrder(orderNo);
    setMessage("");
    setActionError("");
    try {
      const params = new URLSearchParams({ order_no: orderNo, limit: "5000" });
      const response = await api.get<QrControlResponse>(`/api/payroll/qr-labels?${params.toString()}`, 30_000);
      const printable = response.items.filter((row) => Boolean(row.qr_token || row.payload));
      if (!printable.length || printable.length !== response.items.length) {
        throw new Error(t("page.payrollQrControl.noPrintableLabels"));
      }
      const generated = await Promise.all(printable.map(async (row) => ({
        ...row,
        qrSrc: await QRCode.toDataURL(String(row.qr_token || row.payload), {
          errorCorrectionLevel: "L",
          margin: 1,
          width: 240,
          color: { dark: "#111111", light: "#ffffff" },
        }),
      })));
      setPrintRows(generated);
      document.body.classList.add("payroll-qr-reprint-active");
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => window.print());
      });
    } catch (err: any) {
      document.body.classList.remove("payroll-qr-reprint-active");
      setPrintRows([]);
      setActionError(err?.message || t("page.payrollQrControl.reprintFailed"));
    } finally {
      setPrintingOrder(null);
    }
  }

  return (
    <div className="payroll-qr-control-page">
      <PageHeader
        title={t("page.payrollQrControl.title")}
        subtitle={t("page.payrollQrControl.subtitle")}
        actions={(
          <button type="button" className="btn" onClick={() => mutate()} disabled={isLoading}>
            <RefreshCw className={isLoading ? "animate-spin" : ""} />
            {t("page.payroll.refresh")}
          </button>
        )}
      />

      {(error || actionError || message) && (
        <div className={`mb-3 rounded-md border px-3 py-2 text-sm ${error || actionError ? "border-red-200 bg-red-50 text-red-700" : "border-[#ded9ca] bg-[#f8f6ef] text-[#56503f]"}`}>
          {error ? String((error as Error).message || error) : actionError || message}
        </div>
      )}

      <section className="card overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-[#e8e3d6] p-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex flex-1 flex-col gap-2 sm:flex-row">
            <div className="sm:max-w-md sm:flex-1">
              <label className="label" htmlFor="qr-control-search">{t("common.search")}</label>
              <div className="flex h-9 items-center gap-2 rounded-md border border-[#ded9ca] bg-white px-3">
                <Search className="h-4 w-4 shrink-0 text-[#8a8472]" />
                <input
                  id="qr-control-search"
                  className="w-full bg-transparent text-sm outline-none"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t("page.payrollQrControl.searchPlaceholder")}
                />
              </div>
            </div>
            <div className="sm:w-48">
              <label className="label" htmlFor="qr-control-status">{t("common.status")}</label>
              <select id="qr-control-status" className="input h-9 py-1" value={status} onChange={(event) => setStatus(event.target.value as typeof status)}>
                <option value="all">{t("page.payrollQrControl.allStatuses")}</option>
                <option value="available">{t("page.payrollQrControl.notScanned")}</option>
                <option value="scanned">{t("page.payrollQrControl.scanned")}</option>
              </select>
            </div>
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-[#56503f]">
            <span>{t("page.payrollQrControl.total")}: <strong className="text-[#14110b]">{data?.total || 0}</strong></span>
            <span>{t("page.payrollQrControl.notScanned")}: <strong className="text-amber-800">{data?.available_count || 0}</strong></span>
            <span>{t("page.payrollQrControl.scanned")}: <strong className="text-green-800">{data?.scanned_count || 0}</strong></span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="table qr-control-table min-w-[1020px]">
            <thead>
              <tr>
                <th>{t("page.payrollQrControl.qr")}</th>
                <th>{t("page.payrollQrControl.operation")}</th>
                <th>{t("field.batch")}</th>
                <th>{t("page.payrollQrControl.sizeQty")}</th>
                <th>{t("common.status")}</th>
                <th>{t("page.payrollQrControl.employee")}</th>
                <th>{t("page.payrollQrControl.scanTime")}</th>
                <th>{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <Fragment key={group.orderNo}>
                  <tr className="qr-control-group-row">
                    <td colSpan={8}>
                      <div className="flex min-w-0 items-center justify-between gap-4">
                        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
                          <strong className="text-sm text-[#14110b]">{group.orderNo}</strong>
                          <span>{t("common.model")}: <b>{group.models.join(", ") || "-"}</b></span>
                          <span>{t("field.batch")}: <b>{group.batches.join(", ") || "-"}</b></span>
                          <span>{t("page.payrollQrControl.labelCount", { count: group.rows.length })}</span>
                          <span className="text-green-800">{t("page.payrollQrControl.scanned")}: <b>{group.scanned}</b></span>
                          <span className="text-amber-800">{t("page.payrollQrControl.notScanned")}: <b>{group.rows.length - group.scanned}</b></span>
                        </div>
                        <button
                          type="button"
                          className="btn shrink-0"
                          onClick={() => reprintOrder(group.orderNo)}
                          disabled={printingOrder !== null}
                        >
                          <Printer className={printingOrder === group.orderNo ? "animate-pulse" : ""} />
                          {printingOrder === group.orderNo
                            ? t("page.payrollQrControl.reprinting")
                            : t("page.payrollQrControl.reprintOrder")}
                        </button>
                      </div>
                    </td>
                  </tr>
                  {group.rows.map((row) => (
                    <tr key={row.id} className={row.status === "scanned" ? "qr-row-scanned" : "qr-row-available"}>
                      <td>
                        <div className="font-mono text-[11px] font-semibold text-[#14110b]" title={`${t("page.payrollQrControl.issued")}: ${formatDateTime(row.issued_at)}`}>
                          {row.qr_token}
                        </div>
                      </td>
                      <td>
                        <span className="font-medium">{row.operation_name || row.operation_code || "-"}</span>
                        <span className="ml-1 text-[10px] text-[#776f5e]">· {row.operation_code || row.operation_section || "-"}</span>
                      </td>
                      <td className="whitespace-nowrap">{row.batch_no || "-"}</td>
                      <td className="whitespace-nowrap"><b>{row.size || "-"}</b> / {numberText(row.quantity)}</td>
                      <td>
                        <span className={`badge ${row.status === "scanned" ? "badge-green" : "badge-yellow"}`}>
                          {row.status === "scanned"
                            ? t("page.payrollQrControl.scanned")
                            : row.return_count > 0
                              ? t("page.payrollQrControl.returnedAvailable")
                              : t("page.payrollQrControl.notScanned")}
                        </span>
                      </td>
                      <td>
                        <span className="font-medium">{row.employee_name || "-"}</span>
                        {row.department_name && <span className="ml-1 text-[10px] text-[#776f5e]">· {row.department_name}</span>}
                      </td>
                      <td className="whitespace-nowrap" title={formatDateTime(row.last_scanned_at)}>{formatCompactDateTime(row.last_scanned_at)}</td>
                      <td>
                        {row.status === "scanned" && canReturn ? (
                          <button
                            type="button"
                            className="btn btn-danger"
                            onClick={() => returnLabel(row)}
                            disabled={returningId === row.id}
                          >
                            <RotateCcw className={returningId === row.id ? "animate-spin" : ""} />
                            {t("page.payrollQrControl.returnQr")}
                          </button>
                        ) : "-"}
                      </td>
                    </tr>
                  ))}
                </Fragment>
              ))}
              {!isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-10 text-center text-[#8a8472]">
                    {t("page.payrollQrControl.empty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col gap-2 border-t border-[#e8e3d6] px-4 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
          <span className="text-[#6b6251]">{t("page.payrollQrControl.showing", { from, to, total: data?.total || 0 })}</span>
          <div className="flex gap-2">
            <button type="button" className="btn" disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>
              {t("common.previous")}
            </button>
            <button type="button" className="btn" disabled={to >= (data?.total || 0)} onClick={() => setPage((current) => current + 1)}>
              {t("common.next")}
            </button>
          </div>
        </div>
      </section>

      <div className="qr-control-print-sheet hidden" aria-hidden="true">
        {printRows.map((row) => (
          <article className="qr-control-print-label" key={row.id}>
            <div className="qr-control-print-title">{row.operation_name || row.operation_code || "Payroll work"}</div>
            <div className="qr-control-print-body">
              <div className="qr-control-print-details">
                <PrintLine label={t("common.model")} value={row.model_code || "-"} />
                <PrintLine label={t("page.processQr.kroyNo")} value={row.cutting_passport_no || "-"} strong />
                <PrintLine label={t("field.batch")} value={row.batch_no || "-"} />
                <PrintLine
                  label={t("page.processQr.line")}
                  value={row.sewing_line_name && row.sewing_line_name !== row.sewing_line_code
                    ? `${row.sewing_line_code || "-"} - ${row.sewing_line_name}`
                    : row.sewing_line_code || row.sewing_line_name || "-"}
                  strong
                  wrap
                />
                <PrintLine label={t("field.size")} value={row.size || "-"} strong />
                <PrintLine label={t("field.qty")} value={numberText(row.quantity)} strong />
                <PrintLine label={t("page.processQr.rate")} value={`${numberText(row.rate_per_piece)} ${row.currency}`} />
              </div>
              <img className="qr-control-print-code" src={row.qrSrc} alt={row.label_uid} />
            </div>
            <div className="qr-control-print-footer">
              <span>{row.operation_code || row.operation_section || "-"}</span>
              <span>{row.batch_no || row.label_uid}</span>
            </div>
          </article>
        ))}
      </div>

      <style jsx global>{`
        .qr-control-table thead th {
          padding: 6px 8px !important;
          font-size: 10px !important;
        }

        .qr-control-table tbody td {
          padding: 5px 8px !important;
          font-size: 12px;
          line-height: 1.15;
        }

        .qr-control-table .qr-control-group-row td {
          padding: 7px 8px !important;
          border-top: 1px solid #d8d2c2;
          border-bottom: 1px solid #d8d2c2;
          background: #efede6 !important;
          color: #615948;
          font-size: 11px;
        }

        .qr-control-table .qr-row-scanned td {
          background: #edf8ef;
        }

        .qr-control-table .qr-row-available td {
          background: #fff7dc;
        }

        .qr-control-table .qr-row-scanned:hover td {
          background: #e2f3e5;
        }

        .qr-control-table .qr-row-available:hover td {
          background: #fff0bd;
        }

        .qr-control-table .btn {
          min-height: 27px;
          padding: 3px 8px;
          font-size: 11px;
        }

        @media print {
          @page {
            size: 60mm 40mm;
            margin: 0;
          }

          body.payroll-qr-reprint-active * {
            visibility: hidden !important;
          }

          body.payroll-qr-reprint-active .qr-control-print-sheet,
          body.payroll-qr-reprint-active .qr-control-print-sheet * {
            visibility: visible !important;
          }

          body.payroll-qr-reprint-active .qr-control-print-sheet {
            display: block !important;
            position: absolute !important;
            inset: 0 auto auto 0 !important;
            width: 60mm !important;
            margin: 0 !important;
            padding: 0 !important;
          }

          .qr-control-print-label {
            display: flex !important;
            width: 60mm !important;
            height: 40mm !important;
            box-sizing: border-box !important;
            flex-direction: column;
            margin: 0 !important;
            padding: 1.5mm !important;
            overflow: hidden;
            break-after: page;
            page-break-after: always;
            color: #111;
            background: #fff;
            font-family: Arial, sans-serif;
          }

          .qr-control-print-label:last-child {
            break-after: auto;
            page-break-after: auto;
          }

          .qr-control-print-title {
            max-width: 100%;
            overflow: hidden;
            font-size: 7.2pt;
            font-weight: 700;
            line-height: 1;
            white-space: nowrap;
            text-overflow: ellipsis;
          }

          .qr-control-print-body {
            display: flex;
            min-height: 0;
            flex: 1;
            overflow: hidden;
            align-items: stretch;
            gap: 1mm;
          }

          .qr-control-print-details {
            min-width: 0;
            flex: 1;
            overflow: hidden;
            font-size: 5.6pt;
            line-height: 1.03;
          }

          .qr-control-print-line {
            display: grid;
            grid-template-columns: 9mm minmax(0, 1fr);
            min-height: 2.05mm;
            gap: 0.7mm;
            align-items: baseline;
            overflow: hidden;
          }

          .qr-control-print-line > span:first-child {
            min-width: 0;
            overflow: hidden;
            white-space: nowrap;
          }

          .qr-control-print-value {
            min-width: 0;
            max-width: 100%;
            overflow: hidden;
            font-weight: 600;
            white-space: nowrap;
            text-overflow: clip;
          }

          .qr-control-print-value--wrap {
            display: -webkit-box;
            max-height: 4.1mm;
            white-space: normal;
            overflow-wrap: break-word;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
          }

          .qr-control-print-code {
            width: 22mm;
            height: 22mm;
            flex: 0 0 22mm;
            align-self: center;
            object-fit: contain;
            image-rendering: pixelated;
          }

          .qr-control-print-footer {
            display: flex;
            justify-content: space-between;
            gap: 2mm;
            border-top: 0.25mm solid #bbb;
            min-height: 2.5mm;
            margin-top: 0.4mm;
            padding-top: 0.4mm;
            overflow: hidden;
            font-size: 5.5pt;
            font-weight: 700;
            line-height: 1;
            white-space: nowrap;
          }
        }
      `}</style>
    </div>
  );
}

function PrintLine({
  label,
  value,
  strong = false,
  wrap = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
  wrap?: boolean;
}) {
  return (
    <div className="qr-control-print-line">
      <span>{label}</span>
      <span className={`qr-control-print-value ${wrap ? "qr-control-print-value--wrap" : ""} ${strong ? "font-bold" : ""}`}>{value}</span>
    </div>
  );
}
