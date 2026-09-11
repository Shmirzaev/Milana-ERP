"use client";

import type { CtxT } from "@/lib/i18n";
import type { SewingSalarySummaryRow } from "@/lib/sewingProductionReport";

export default function SewingSalarySummaryTable({ rows, days, lang, t }: {
  rows: SewingSalarySummaryRow[];
  days: string[];
  lang: string;
  t: CtxT;
}) {
  const totals = new Map<string, { amount: number; daily: Record<string, number> }>();
  for (const row of rows) {
    const total = totals.get(row.currency) || { amount: 0, daily: {} };
    total.amount += Number(row.total_amount);
    for (const [day, amount] of Object.entries(row.daily_amounts)) total.daily[day] = (total.daily[day] || 0) + Number(amount);
    totals.set(row.currency, total);
  }
  const number = (value: number | string) => Number(value).toLocaleString(lang, { maximumFractionDigits: 2 });
  const dateLabel = (day: string) => `${day.slice(8, 10)}.${day.slice(5, 7)}`;
  const printPages: string[][] = [];
  for (let offset = 0; offset < days.length; offset += 31) printPages.push(days.slice(offset, offset + 31));
  if (!printPages.length) printPages.push([]);

  function table(visibleDays: string[], printing = false) {
    return (
      <table className="table sewing-salary-table text-xs" style={printing ? undefined : { minWidth: 600 + visibleDays.length * 95 }}>
        <thead>
          <tr>
            <th className="salary-number">#</th>
            <th className="salary-employee">{t("page.sewingReport.employee")}</th>
            {visibleDays.map((day) => <th key={day} title={day} className="text-right whitespace-nowrap">{dateLabel(day)}</th>)}
            <th className="text-right">{t("page.sewingReport.records")}</th>
            <th className="text-right">{t("page.sewingReport.quantity")}</th>
            <th className="salary-total text-right">{t("page.sewingReport.totalSalary")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={visibleDays.length + 5} className="py-10 text-center text-[#8a8472]">{t("page.sewingReport.empty")}</td></tr>}
          {rows.map((row, index) => (
            <tr key={`${row.employee_id}-${row.currency}`}>
              <td>{index + 1}</td>
              <td>
                <div>{row.employee_name}</div>
                {row.employee_no && <div className="text-xs text-[#8a8472]">{row.employee_no}</div>}
              </td>
              {visibleDays.map((day) => <td key={day} className="text-right tabular-nums">{number(row.daily_amounts[day] || 0)}</td>)}
              <td className="text-right tabular-nums">{number(row.record_count)}</td>
              <td className="text-right tabular-nums">{number(row.quantity)}</td>
              <td className="text-right font-semibold tabular-nums">{number(row.total_amount)} {row.currency}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          {[...totals].sort(([a], [b]) => a.localeCompare(b)).map(([currency, total]) => (
            <tr key={currency}>
              <td colSpan={2} className="font-semibold">{t("page.sewingReport.totalSalary")} ({currency})</td>
              {visibleDays.map((day) => <td key={day} className="text-right font-semibold tabular-nums">{number(total.daily[day] || 0)}</td>)}
              <td />
              <td />
              <td className="text-right font-semibold tabular-nums">{number(total.amount)} {currency}</td>
            </tr>
          ))}
        </tfoot>
      </table>
    );
  }

  return (
    <>
      <div className="overflow-x-auto no-print">{table(days)}</div>
      <div className="hidden print:block">
        {printPages.map((pageDays, index) => (
          <div className="salary-print-page" key={pageDays[0] || index}>
            {printPages.length > 1 && <p className="mb-2 text-xs">{pageDays[0]} — {pageDays[pageDays.length - 1]}</p>}
            {table(pageDays, true)}
          </div>
        ))}
      </div>
    </>
  );
}
