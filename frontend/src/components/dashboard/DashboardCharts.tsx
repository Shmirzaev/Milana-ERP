"use client";
import { stageColors } from "./types";

const number = (n: number) => n.toLocaleString();

export function OrderDonut({ rows, total, label }: { rows: { label: string; value: number; color: string }[]; total: number; label: string }) {
  let offset = 0;
  return <div className="px-5 pb-5">
    <svg viewBox="0 0 240 210" className="mx-auto h-52 w-60 max-w-full" role="img" aria-label={`${label}: ${total}. ${rows.map(r => `${r.label}: ${r.value}`).join(", ")}`}>
      <circle cx="120" cy="105" r="76" fill="none" stroke="var(--erp-surface-muted)" strokeWidth="22" />
      {rows.map(row => {
        const length = total ? row.value / total * 100 : 0;
        const previous = offset; offset += length;
        return <circle key={row.label} cx="120" cy="105" r="76" pathLength="100" fill="none" stroke={row.color} strokeWidth="22" strokeDasharray={`${Math.max(0, length - (length < 100 ? .7 : 0))} ${100 - Math.max(0, length - (length < 100 ? .7 : 0))}`} strokeDashoffset={-previous} transform="rotate(-90 120 105)"><title>{row.label}: {row.value} ({total ? Math.round(row.value / total * 100) : 0}%)</title></circle>;
      })}
      <text x="120" y="104" textAnchor="middle" fill="var(--erp-text)" fontSize="36" fontWeight="600">{number(total)}</text><text x="120" y="128" textAnchor="middle" fill="var(--erp-text-soft)" fontSize="12">{label}</text>
    </svg>
    <div className="space-y-2.5">{rows.map(r => <div key={r.label} className="flex items-center gap-2 text-sm"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: r.color }} /><span className="flex-1">{r.label}</span><span className="tabular-nums">{r.value}</span><span className="w-11 text-right tabular-nums" style={{ color: "var(--erp-text-soft)" }}>{total ? Math.round(r.value / total * 100) : 0}%</span></div>)}</div>
  </div>;
}

export function DepartmentBars({ values, labels, title }: { values: number[]; labels: string[]; title: string }) {
  const max = Math.max(1, ...values);
  return <div className="px-5 pb-5 pt-6" role="img" aria-label={`${title}: ${labels.map((l, i) => `${l} ${values[i]}`).join(", ")}`}>
    {values.map((v, i) => <div key={labels[i]} className="mb-6 last:mb-0"><div className="mb-2 flex justify-between text-sm"><span>{labels[i]}</span><span className="font-semibold tabular-nums">{number(v)}</span></div><div className="h-5 w-full rounded-sm" style={{ background: "var(--erp-surface-muted)" }}><div className="h-full rounded-sm" style={{ width: `${v / max * 100}%`, background: stageColors[i] }} /></div></div>)}
  </div>;
}
