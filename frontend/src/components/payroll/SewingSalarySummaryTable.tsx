"use client";

import type { CtxT } from "@/lib/i18n";
import type { SewingSalarySummaryRow } from "@/lib/sewingProductionReport";

export default function SewingSalarySummaryTable({ rows, lang, t }: {
  rows: SewingSalarySummaryRow[];
  lang: string;
  t: CtxT;
}) {
  const totals = new Map<string, number>();
  for (const row of rows) totals.set(row.currency, (totals.get(row.currency) || 0) + Number(row.total_amount));
  const number = (value: number | string) => Number(value).toLocaleString(lang, { maximumFractionDigits: 2 });

  return (
    <div className="overflow-x-auto">
      <table className="table min-w-[650px] text-sm">
        <thead>
          <tr>
            <th>#</th>
            <th>{t("page.sewingReport.employee")}</th>
            <th className="text-right">{t("page.sewingReport.records")}</th>
            <th className="text-right">{t("page.sewingReport.quantity")}</th>
            <th className="text-right">{t("page.sewingReport.totalSalary")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={5} className="py-10 text-center text-[#8a8472]">{t("page.sewingReport.empty")}</td></tr>}
          {rows.map((row, index) => (
            <tr key={`${row.employee_id}-${row.currency}`}>
              <td>{index + 1}</td>
              <td>
                <div>{row.employee_name}</div>
                {row.employee_no && <div className="text-xs text-[#8a8472]">{row.employee_no}</div>}
              </td>
              <td className="text-right tabular-nums">{number(row.record_count)}</td>
              <td className="text-right tabular-nums">{number(row.quantity)}</td>
              <td className="text-right font-semibold tabular-nums">{number(row.total_amount)} {row.currency}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          {[...totals].sort(([a], [b]) => a.localeCompare(b)).map(([currency, amount]) => (
            <tr key={currency}>
              <td colSpan={4} className="font-semibold">{t("page.sewingReport.totalSalary")} ({currency})</td>
              <td className="text-right font-semibold tabular-nums">{number(amount)} {currency}</td>
            </tr>
          ))}
        </tfoot>
      </table>
    </div>
  );
}
