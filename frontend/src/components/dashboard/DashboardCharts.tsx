"use client";
import { useEffect, useRef, useState } from "react";
import { DailyOutput, stageColors, stageKeys } from "./types";

const number = (n: number) => n.toLocaleString();

export function OutputLineChart({ points, labels, title }: { points: DailyOutput[]; labels: string[]; title: string }) {
  const [selected, setSelected] = useState<number | null>(null);
  const [hidden, setHidden] = useState<string[]>([]);
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(790);
  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.min(790, entry.contentRect.width))));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const max = Math.max(4, ...points.flatMap(p => stageKeys.filter(k => !hidden.includes(k)).map(k => p[k])));
  const ceiling = Math.ceil(max / 4) * 4;
  const plotWidth = width - 90;
  const x = (i: number) => 58 + i * plotWidth / Math.max(1, points.length - 1);
  const y = (v: number) => 242 - v / ceiling * 210;
  const current = points[selected ?? points.length - 1];
  return <div ref={container}>
    <div className="flex flex-wrap gap-x-5 gap-y-2 px-5 pt-4">
      {stageKeys.map((k, i) => <button key={k} aria-pressed={!hidden.includes(k)} onClick={() => setHidden(hidden.includes(k) ? hidden.filter(v => v !== k) : [...hidden, k])} className="flex items-center gap-2 text-sm" style={{ opacity: hidden.includes(k) ? .4 : 1 }}><span className="h-0.5 w-5" style={{ background: stageColors[i] }} />{labels[i]}</button>)}
    </div>
    <svg viewBox={`0 0 ${width} 285`} className="mt-2 w-full" role="img" aria-label={title}>
      {[0, 1, 2, 3, 4].map(i => <g key={i}><line x1="58" x2={width - 32} y1={y(i * ceiling / 4)} y2={y(i * ceiling / 4)} stroke="var(--erp-border-soft)" /><text x="48" y={y(i * ceiling / 4) + 4} textAnchor="end" fill="var(--erp-text-soft)" fontSize="11">{number(i * ceiling / 4)}</text></g>)}
      {points.map((p, i) => i === 0 || i === points.length - 1 || (i % Math.max(1, Math.ceil(points.length / (width < 450 ? 3 : 7))) === 0 && i < points.length - (width < 450 ? 5 : 2)) ? <text key={p.date} x={x(i)} y="268" textAnchor="middle" fill="var(--erp-text-soft)" fontSize="11">{p.date.slice(5).replace("-", "/")}</text> : null)}
      {selected !== null && <line x1={x(selected)} x2={x(selected)} y1="28" y2="242" stroke="var(--erp-border-strong)" strokeDasharray="4 4" />}
      {stageKeys.filter(k => !hidden.includes(k)).map(k => <g key={k}>
        <path d={points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p[k])}`).join(" ")} fill="none" stroke={stageColors[stageKeys.indexOf(k)]} strokeWidth="2.5" strokeLinejoin="round" />
        {points.map((p, i) => <circle key={p.date} cx={x(i)} cy={y(p[k])} r={i === selected ? 5 : points.length <= 7 ? 3 : 0} fill={stageColors[stageKeys.indexOf(k)]} />)}
      </g>)}
      {points.map((p, i) => <rect key={p.date} x={x(i) - plotWidth / 2 / Math.max(1, points.length - 1)} y="20" width={plotWidth / Math.max(1, points.length - 1)} height="230" fill="transparent" onMouseEnter={() => setSelected(i)} onClick={() => setSelected(i)} onFocus={() => setSelected(i)} tabIndex={0} role="button" aria-label={`${p.date}: ${stageKeys.map((k, n) => `${labels[n]} ${p[k]}`).join(", ")}`}><title>{p.date}: {stageKeys.map((k, n) => `${labels[n]} ${number(p[k])}`).join(" · ")}</title></rect>)}
    </svg>
    {current && <div className="flex flex-wrap gap-x-4 gap-y-2 border-t px-5 py-3 text-xs" style={{ borderColor: "var(--erp-border-soft)", color: "var(--erp-text-soft)" }}><span>{current.date}</span>{stageKeys.map((k, i) => <span key={k}>{labels[i]} <strong style={{ color: stageColors[i] }}>{number(current[k])}</strong></span>)}</div>}
  </div>;
}

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
