import { useEffect, useRef, useState } from "react";
import type { DashboardCopy } from "./messages";
import type { ReportFormatting } from "./ReportSections";
import { stageKeys, type DateRange, type Stage } from "./report";
import styles from "./dashboard.module.css";

type Point = DateRange & { values: Record<Stage, number> };

export function ProductionChart({ points, activeIndex, onSelect, copy, format }: {
  points: Point[]; activeIndex: number; onSelect: (index: number) => void; copy: DashboardCopy; format: ReportFormatting;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(230, Math.round(entry.contentRect.width))));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const height = 178;
  const top = 9;
  const base = 148;
  const maximum = Math.max(1, ...points.flatMap(point => stageKeys.map(stage => point.values[stage])));
  const order = 10 ** Math.floor(Math.log10(maximum / 3));
  const step = Math.max(1, Math.ceil(maximum / (order * 3)) * order);
  const left = Math.max(37, format.count(step * 3).length * 7 + 12);
  const right = width - 12;
  const xFor = (index: number) => left + index / Math.max(points.length - 1, 1) * (right - left);
  const yFor = (value: number) => base - value / (step * 3) * (base - top);
  const single = points.length === 1;
  const active = points[activeIndex];
  const tickCount = Math.min(points.length, width < 420 ? 3 : 5);
  const ticks = Array.from({ length: tickCount }, (_, i) => Math.round(i * (points.length - 1) / Math.max(tickCount - 1, 1)));
  const barSpacing = (right - left) / stageKeys.length;
  const barWidth = Math.min(36, barSpacing * .55);

  return <div ref={container} className={styles.chart}>
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={copy.trendHint}>
      {[3, 2, 1, 0].map(tick => <g key={tick}>
        <line className={styles.gridline} x1={left} x2={right} y1={yFor(tick * step)} y2={yFor(tick * step)} />
        <text className={styles.axis} x={left - 9} y={yFor(tick * step) + 4} textAnchor="end">{format.count(tick * step)}</text>
      </g>)}
      {single ? stageKeys.map((stage, i) => {
        const value = points[0].values[stage];
        const x = left + barSpacing * (i + .5);
        return <g key={stage} className={styles[stage]}>
          <rect className={styles.column} x={x - barWidth / 2} y={yFor(value) - (value === 0 ? 2 : 0)}
            width={barWidth} height={Math.max(2, base - yFor(value))} rx="3" />
          <text className={styles.axis} x={x} y={171} textAnchor="middle">{copy[stage]}</text>
        </g>;
      }) : <>
        {active && <line className={styles.cursor} x1={xFor(activeIndex)} x2={xFor(activeIndex)} y1={top} y2={base} />}
        {stageKeys.map(stage => <g key={stage} className={styles[stage]}>
          <path className={styles.chartLine} d={points.map((point, i) => `${i ? "L" : "M"}${xFor(i)},${yFor(point.values[stage])}`).join(" ")} />
          {active && <circle className={styles.marker} cx={xFor(activeIndex)} cy={yFor(active.values[stage])} r={4} />}
        </g>)}
        {ticks.map((i, tick) => <text key={i} className={styles.axis} x={xFor(i)} y={171}
          textAnchor={tick === 0 ? "start" : tick === ticks.length - 1 ? "end" : "middle"}>{format.axis(points[i].end)}</text>)}
        <rect x={left - 5} y={top} width={right - left + 10} height={base - top} fill="transparent"
          onClick={event => {
            if (points.length < 2) return;
            const { left: offset, width: renderedWidth } = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
            const x = (event.clientX - offset) / renderedWidth * width;
            onSelect(Math.min(points.length - 1, Math.max(0, Math.round((x - left) / (right - left) * (points.length - 1)))));
          }} />
      </>}
    </svg>
  </div>;
}
