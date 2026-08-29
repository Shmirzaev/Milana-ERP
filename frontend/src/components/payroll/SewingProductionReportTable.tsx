"use client";

import type { SewingProductionReportRow } from "@/lib/sewingProductionReport";
import type { CtxT } from "@/lib/i18n";

type Props = {
  rows: SewingProductionReportRow[];
  rowOffset: number;
  lang: string;
  t: CtxT;
};

function money(value: number | string, currency: string, lang: string) {
  return `${Number(value || 0).toLocaleString(lang, { maximumFractionDigits: 2 })} ${currency}`;
}

export default function SewingProductionReportTable({ rows, rowOffset, lang, t }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="table min-w-[1500px] text-xs no-print">
        <thead>
          <tr>
            <th className="w-12">#</th>
            <th>{t("page.sewingReport.date")}</th>
            <th>{t("page.sewingReport.employee")}</th>
            <th>{t("page.sewingReport.barcode")}</th>
            <th>{t("page.sewingReport.line")}</th>
            <th>{t("page.sewingReport.cutting")}</th>
            <th>{t("page.sewingReport.model")}</th>
            <th>{t("page.sewingReport.product")}</th>
            <th>{t("page.sewingReport.operation")}</th>
            <th className="text-right">{t("page.sewingReport.quantity")}</th>
            <th className="text-right">{t("page.sewingReport.rate")}</th>
            <th className="text-right">{t("page.sewingReport.amount")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={12} className="py-10 text-center text-[#8a8472]">{t("page.sewingReport.empty")}</td>
            </tr>
          )}
          {rows.map((row, index) => (
            <tr key={row.id}>
              <td>{rowOffset + index + 1}</td>
              <td className="whitespace-nowrap">{new Date(row.scanned_at).toLocaleString(lang)}</td>
              <td>
                <div className="font-medium text-[#14110b]">{row.employee_name}</div>
                <div className="text-[11px] text-[#8a8472]">{row.employee_no || `#${row.employee_id}`}</div>
              </td>
              <td className="font-mono">{row.barcode}</td>
              <td>
                <div>{row.sewing_line_code || "-"}</div>
                {row.sewing_line_name && row.sewing_line_name !== row.sewing_line_code && (
                  <div className="text-[11px] text-[#8a8472]">{row.sewing_line_name}</div>
                )}
              </td>
              <td>
                <div>{row.cutting_reference || "-"}</div>
                <div className="text-[11px] text-[#8a8472]">{row.sales_order_no || row.production_no || ""}</div>
              </td>
              <td>
                <div>{row.model_code || "-"}</div>
                {row.size && <div className="text-[11px] text-[#8a8472]">{t("page.sewingReport.size")}: {row.size}</div>}
              </td>
              <td>{row.product_name || "-"}</td>
              <td>
                <div>{row.operation_name || row.operation_code || "-"}</div>
                {row.operation_code && row.operation_name !== row.operation_code && (
                  <div className="text-[11px] text-[#8a8472]">{row.operation_code}</div>
                )}
              </td>
              <td className="text-right tabular-nums">{Number(row.quantity || 0).toLocaleString(lang)}</td>
              <td className="text-right tabular-nums">{money(row.rate_per_piece, row.currency, lang)}</td>
              <td className="text-right font-semibold tabular-nums">{money(row.total_amount, row.currency, lang)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <table className="sewing-report-print-table hidden w-full text-xs print:table">
        <thead>
          <tr>
            <th className="w-10">#</th>
            <th>{t("page.sewingReport.date")}</th>
            <th>{t("page.sewingReport.employee")}</th>
            <th>{t("page.sewingReport.barcode")}</th>
            <th>{t("page.sewingReport.model")} / {t("page.sewingReport.size")}</th>
            <th>{t("page.sewingReport.operation")}</th>
            <th className="text-right">{t("page.sewingReport.quantity")}</th>
            <th className="text-right">{t("page.sewingReport.rate")}</th>
            <th className="text-right">{t("page.sewingReport.amount")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={9} className="py-10 text-center">{t("page.sewingReport.empty")}</td>
            </tr>
          )}
          {rows.map((row, index) => (
            <tr key={`print-${row.id}`}>
              <td>{rowOffset + index + 1}</td>
              <td className="whitespace-nowrap">{new Date(row.scanned_at).toLocaleString(lang)}</td>
              <td>{row.employee_name}</td>
              <td className="font-mono">{row.barcode}</td>
              <td>{[row.model_code, row.size].filter(Boolean).join(" / ") || "-"}</td>
              <td>{row.operation_name || row.operation_code || "-"}</td>
              <td className="text-right tabular-nums">{Number(row.quantity || 0).toLocaleString(lang)}</td>
              <td className="text-right tabular-nums">{money(row.rate_per_piece, row.currency, lang)}</td>
              <td className="text-right tabular-nums">{money(row.total_amount, row.currency, lang)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
