"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Metrics = { passports: number; fabric_kg: number; fabric_m: number; rolls: number; pieces: number };
type Report = { totals: Metrics; daily: (Metrics & { date: string })[] };
const measures = ["fabric_kg", "fabric_m", "rolls", "pieces"] as const;

export default function CuttingPassportDashboard({ query, invalid }: { query: string; invalid: boolean }) {
  const { t, lang } = useT();
  const { data, error, isLoading, mutate } = useSWR<Report>(invalid ? null : `/api/cutting-passports/dashboard?${query}`, fetcher);
  const number = (value: number) => value.toLocaleString(lang, { maximumFractionDigits: 3 });
  if (invalid) return null;
  if (error) return <div role="alert" className="card p-4"><p>{t("passportReport.loadError")}</p><button className="btn mt-3" onClick={() => void mutate()}>{t("common.retry")}</button></div>;
  if (isLoading || !data) return <p role="status" className="py-8 text-sm text-slate-500">{t("common.loading")}</p>;
  return <section aria-label={t("passportReport.dashboard")} className="space-y-5">
    <p className="text-sm text-slate-600">{t("passportReport.basis")}</p>
    {!data.totals.passports ? <div className="card p-8 text-center text-sm text-slate-500">{t("passportReport.empty")}</div> : <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {measures.map((measure) => {
          const values = data.daily.map((day) => day[measure]);
          const max = Math.max(...values, 1);
          const first = Date.parse(data.daily[0].date);
          const span = Date.parse(data.daily[data.daily.length - 1].date) - first;
          const points = values.map((value, index) => `${span ? (Date.parse(data.daily[index].date) - first) * 280 / span : 140},${65 - value * 55 / max}`).join(" ");
          return <div key={measure} className="card p-4" data-metric={measure}>
            <h2 className="text-sm text-slate-600">{t(`passportReport.${measure}`)}</h2>
            <p className="mt-2 text-2xl font-semibold tabular-nums">{number(data.totals[measure])}</p>
            <svg viewBox="0 0 280 75" className="mt-4 h-20 w-full text-[#8d8151]" role="img" aria-label={t("passportReport.dailyTrend", { metric: t(`passportReport.${measure}`) })}>
              <path d="M0 70H280" stroke="currentColor" opacity="0.2" />
              <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
              {values.length === 1 && <circle cx="140" cy={65 - values[0] * 55 / max} r="3" fill="currentColor" />}
            </svg>
            <div className="flex justify-between text-xs text-slate-500"><span>{data.daily[0]?.date}</span><span>{data.daily[data.daily.length - 1]?.date}</span></div>
          </div>;
        })}
      </div>
      <p className="text-sm text-slate-600">{t("passportReport.tepaHint")}</p>
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <caption className="p-4 text-left font-semibold">{t("passportReport.daily")}</caption>
          <thead className="border-y border-slate-200 bg-slate-50 text-slate-600"><tr>
            <th className="px-4 py-3 text-left">{t("page.cuttingPassports.field.date")}</th>
            <th className="px-4 py-3 text-right">{t("passportReport.passports")}</th>
            {measures.map((key) => <th key={key} className="whitespace-nowrap px-4 py-3 text-right">{t(`passportReport.${key}`)}</th>)}
          </tr></thead>
          <tbody>{[...data.daily].reverse().map((day) => <tr key={day.date} className="border-b border-slate-100">
            <td className="whitespace-nowrap px-4 py-3">{day.date}</td>
            <td className="px-4 py-3 text-right tabular-nums">{number(day.passports)}</td>
            {measures.map((key) => <td key={key} className="px-4 py-3 text-right tabular-nums">{number(day[key])}</td>)}
          </tr>)}</tbody>
          <tfoot className="border-t border-slate-200 font-semibold"><tr>
            <td className="px-4 py-3">{t("common.total")}</td><td className="px-4 py-3 text-right">{number(data.totals.passports)}</td>
            {measures.map((key) => <td key={key} className="px-4 py-3 text-right tabular-nums">{number(data.totals[key])}</td>)}
          </tr></tfoot>
        </table>
      </div>
    </>}
  </section>;
}
