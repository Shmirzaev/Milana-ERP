"use client";
import { useEffect, useRef, useState } from "react";
import { ChartNoAxesCombined } from "lucide-react";
import { activityText } from "./messages";

type Point = { date: string; values: Record<string, number> };
type Series = { key: string; label: string; color: string };
type Props = {
  points: Point[];
  series: Series[];
  title: string;
  copy: typeof activityText.en;
  onWiden?: () => void;
};

const number = (value: number) => value.toLocaleString();

export default function ActivityLineChart({ points, series, title, copy, onWiden }: Props) {
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

  const totals = Object.fromEntries(series.map(item => [item.key, points.reduce((sum, point) => sum + (point.values[item.key] || 0), 0)]));
  const available = series.filter(item => totals[item.key] > 0);
  const visible = available.filter(item => !hidden.includes(item.key));
  const max = Math.max(1, ...points.flatMap(point => visible.map(item => point.values[item.key] || 0)));
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const ceiling = Math.max(5, Math.ceil(max / magnitude) * magnitude);
  const plotWidth = width - 90;
  const x = (index: number) => 58 + (points.length === 1 ? plotWidth / 2 : index * plotWidth / Math.max(1, points.length - 1));
  const y = (value: number) => 232 - value / ceiling * 190;
  const index = Math.min(selected ?? points.length - 1, points.length - 1);
  const current = points[index];
  const tickEvery = Math.max(1, Math.ceil((points.length - 1) / (width < 450 ? 3 : 6)));

  return (
    <div ref={container}>
      <div className="mx-5 mt-4 flex flex-wrap gap-x-6 gap-y-3 border-b pb-4" style={{ borderColor: "var(--erp-border-soft)" }}>
        {series.map(item => (
          <button
            key={item.key}
            aria-label={item.label}
            aria-pressed={totals[item.key] > 0 && !hidden.includes(item.key)}
            disabled={!totals[item.key]}
            title={`${item.label} · ${copy.period}`}
            onClick={() => setHidden(hidden.includes(item.key) ? hidden.filter(key => key !== item.key) : [...hidden, item.key])}
            className="min-w-24 text-left"
            style={{ opacity: hidden.includes(item.key) ? .45 : 1 }}
          >
            <span className="flex items-center gap-2 text-xs" style={{ color: "var(--erp-text-soft)" }}>
              <span className="h-0.5 w-4" style={{ background: totals[item.key] ? item.color : "var(--erp-border-strong)" }} />{item.label}
            </span>
            <span className={`mt-1 block ${totals[item.key] ? "text-xl font-semibold tabular-nums" : "text-sm"}`} style={{ color: totals[item.key] ? "var(--erp-text)" : "var(--erp-text-soft)" }}>
              {totals[item.key] ? number(totals[item.key]) : copy.noOutput}
            </span>
          </button>
        ))}
        <span className="ml-auto self-end text-xs" style={{ color: "var(--erp-text-soft)" }}>{copy.period}</span>
      </div>
      {!available.length ? (
        <div className="flex min-h-40 flex-col items-center justify-center gap-3 px-5 py-7 text-center text-sm" style={{ color: "var(--erp-text-soft)" }}>
          <ChartNoAxesCombined size={24} aria-hidden="true" />
          <p>{copy.empty}</p>
          {onWiden && <button className="btn" onClick={onWiden}>{copy.more}</button>}
        </div>
      ) : !visible.length ? (
        <div role="status" className="flex min-h-40 items-center justify-center p-5 text-sm" style={{ color: "var(--erp-text-soft)" }}>{copy.noVisible}</div>
      ) : (
        <>
          <svg viewBox={`0 0 ${width} 275`} className="mt-1 w-full" role="img" aria-label={title}>
            {[0, 1, 2, 3, 4, 5].map(tick => (
              <g key={tick}>
                <line x1="58" x2={width - 32} y1={y(tick * ceiling / 5)} y2={y(tick * ceiling / 5)} stroke="var(--erp-border-soft)" />
                <text x="48" y={y(tick * ceiling / 5) + 4} textAnchor="end" fill="var(--erp-text-soft)" fontSize="11">{number(tick * ceiling / 5)}</text>
              </g>
            ))}
            {points.map((point, i) => i === 0 || i === points.length - 1 || (i % tickEvery === 0 && points.length - 1 - i >= tickEvery / 2) ? (
              <text key={point.date} x={x(i)} y="257" textAnchor="middle" fill="var(--erp-text-soft)" fontSize="11">{point.date.slice(5).replace("-", "/")}</text>
            ) : null)}
            {current && <line x1={x(index)} x2={x(index)} y1="30" y2="232" stroke="var(--erp-border-strong)" strokeDasharray="4 4" />}
            {visible.map(item => {
              const line = points.map((point, i) => `${i ? "L" : "M"}${x(i)},${y(point.values[item.key] || 0)}`).join(" ");
              return (
                <g key={item.key}>
                  <path d={`${line} L${x(points.length - 1)},232 L${x(0)},232 Z`} fill={item.color} fillOpacity="0.08" />
                  <path d={line} fill="none" stroke={item.color} strokeWidth="2.5" strokeLinejoin="round" />
                  {points.map((point, i) => <circle key={point.date} cx={x(i)} cy={y(point.values[item.key] || 0)} r={i === index ? 4.5 : points.length <= 7 ? 3 : 0} fill="var(--erp-surface)" stroke={item.color} strokeWidth="2" />)}
                </g>
              );
            })}
            {points.map((point, i) => (
              <rect key={point.date} x={x(i) - plotWidth / 2 / Math.max(1, points.length - 1)} y="28" width={plotWidth / Math.max(1, points.length - 1)} height="209" fill="transparent"
                onMouseEnter={() => setSelected(i)} onClick={() => setSelected(i)} onFocus={() => setSelected(i)}
                onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(i); } }}
                tabIndex={0} role="button" aria-label={`${point.date}: ${series.map(item => `${item.label} ${point.values[item.key] || 0}`).join(", ")}`}>
                <title>{point.date}: {series.map(item => `${item.label} ${number(point.values[item.key] || 0)}`).join(" · ")}</title>
              </rect>
            ))}
          </svg>
          {current && <div className="flex flex-wrap gap-x-5 gap-y-2 border-t px-5 py-3 text-sm" style={{ borderColor: "var(--erp-border-soft)", color: "var(--erp-text-soft)" }}>
            <span className="text-xs">{copy.selected}<span className="mt-1 block tabular-nums" style={{ color: "var(--erp-text)" }}>{current.date}</span></span>
            {visible.map(item => <span key={item.key} className="text-xs">{item.label}<strong className="mt-1 block text-sm tabular-nums" style={{ color: item.color }}>{number(current.values[item.key] || 0)}</strong></span>)}
          </div>}
        </>
      )}
    </div>
  );
}
