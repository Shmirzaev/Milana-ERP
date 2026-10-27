"use client";

type ChartPoint = {
  label: string;
  tooltipLabel?: string;
  values: Record<string, number>;
};

type ChartSeries = {
  key: string;
  label: string;
  color: string;
};

type ForecastLineChartProps = {
  title: string;
  description: string;
  points: ChartPoint[];
  series: ChartSeries[];
  emptyLabel: string;
  valueFormatter?: (value: number) => string;
};

const WIDTH = 760;
const HEIGHT = 292;
const PADDING = { top: 24, right: 24, bottom: 54, left: 58 };
const Y_TICKS = 4;

function safeNumber(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
}

export default function ForecastLineChart({
  title,
  description,
  points,
  series,
  emptyLabel,
  valueFormatter = (value) => value.toLocaleString(undefined, { maximumFractionDigits: 1 }),
}: ForecastLineChartProps) {
  const chartWidth = WIDTH - PADDING.left - PADDING.right;
  const chartHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const maxValue = Math.max(
    1,
    ...points.flatMap((point) => series.map((item) => safeNumber(point.values[item.key]))),
  );
  const roundedMax = Math.ceil(maxValue / Y_TICKS) * Y_TICKS;
  const xFor = (index: number) => (
    points.length <= 1
      ? PADDING.left + chartWidth / 2
      : PADDING.left + (index * chartWidth) / (points.length - 1)
  );
  const yFor = (value: number) => PADDING.top + chartHeight - (safeNumber(value) / roundedMax) * chartHeight;

  return (
    <section className="card min-w-0">
      <div className="border-b border-[#ecebe3] px-4 py-3">
        <h2 className="app-card-title">{title}</h2>
        <p className="mt-1 text-xs leading-5 text-[#8a8472]">{description}</p>
      </div>

      {points.length === 0 ? (
        <div className="flex min-h-[292px] items-center justify-center px-4 text-sm text-[#8a8472]">
          {emptyLabel}
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-x-5 gap-y-2 px-4 pt-3" aria-hidden="true">
            {series.map((item) => (
              <div key={item.key} className="flex items-center gap-2 text-xs text-[#56503f]">
                <span className="h-0.5 w-5" style={{ backgroundColor: item.color }} />
                {item.label}
              </div>
            ))}
          </div>

          <div className="overflow-x-auto px-2 pb-2">
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="h-[292px] min-w-[620px] w-full"
              role="img"
              aria-label={`${title}. ${description}`}
            >
              {Array.from({ length: Y_TICKS + 1 }, (_, index) => {
                const value = (roundedMax / Y_TICKS) * (Y_TICKS - index);
                const y = PADDING.top + (index * chartHeight) / Y_TICKS;
                return (
                  <g key={value}>
                    <line
                      x1={PADDING.left}
                      x2={WIDTH - PADDING.right}
                      y1={y}
                      y2={y}
                      stroke="var(--erp-border-soft)"
                      strokeWidth="1"
                    />
                    <text
                      x={PADDING.left - 10}
                      y={y + 4}
                      textAnchor="end"
                      fill="var(--erp-text-muted)"
                      fontSize="11"
                    >
                      {valueFormatter(value)}
                    </text>
                  </g>
                );
              })}

              {points.map((point, index) => (
                <text
                  key={`${point.label}-${index}`}
                  x={xFor(index)}
                  y={HEIGHT - 22}
                  textAnchor="middle"
                  fill="var(--erp-text-muted)"
                  fontSize="11"
                >
                  {point.label}
                </text>
              ))}

              {series.map((item) => {
                const path = points
                  .map((point, index) => `${index === 0 ? "M" : "L"} ${xFor(index)} ${yFor(point.values[item.key])}`)
                  .join(" ");
                return (
                  <g key={item.key}>
                    <path
                      d={path}
                      fill="none"
                      stroke={item.color}
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      vectorEffect="non-scaling-stroke"
                    />
                    {points.map((point, index) => {
                      const value = safeNumber(point.values[item.key]);
                      return (
                        <circle
                          key={`${item.key}-${point.label}-${index}`}
                          cx={xFor(index)}
                          cy={yFor(value)}
                          r="3.5"
                          fill="var(--erp-surface)"
                          stroke={item.color}
                          strokeWidth="2"
                          vectorEffect="non-scaling-stroke"
                        >
                          <title>{`${point.tooltipLabel || point.label}: ${item.label} ${valueFormatter(value)}`}</title>
                        </circle>
                      );
                    })}
                  </g>
                );
              })}
            </svg>
          </div>

          <table className="sr-only">
            <caption>{title}</caption>
            <thead>
              <tr>
                <th scope="col">{title}</th>
                {series.map((item) => <th key={item.key} scope="col">{item.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {points.map((point, index) => (
                <tr key={`${point.label}-accessible-${index}`}>
                  <th scope="row">{point.tooltipLabel || point.label}</th>
                  {series.map((item) => (
                    <td key={item.key}>{valueFormatter(safeNumber(point.values[item.key]))}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
