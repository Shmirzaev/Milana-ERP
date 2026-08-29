type ShipmentItemLine = {
  id?: number | string;
  model_code?: string | null;
  model_name?: string | null;
  color?: string | null;
  size?: string | null;
  quantity?: number | string | null;
};

export default function ShipmentItemLines({ items }: { items?: ShipmentItemLine[] | null }) {
  if (!Array.isArray(items) || items.length === 0) {
    return <span style={{ color: "var(--erp-text-muted)" }}>-</span>;
  }

  return (
    <div className="min-w-[220px] space-y-1.5">
      {items.map((item, index) => {
        const model = item.model_code || item.model_name || "-";
        const variant = [item.color, item.size].filter(Boolean).join(" / ");
        return (
          <div
            key={item.id ?? `${model}-${variant}-${index}`}
            className="flex items-start justify-between gap-3 text-xs"
          >
            <span className="min-w-0">
              <span className="font-medium" style={{ color: "var(--erp-text)" }}>{model}</span>
              {variant && (
                <span className="block" style={{ color: "var(--erp-text-muted)" }}>{variant}</span>
              )}
            </span>
            <span className="shrink-0 font-medium tabular-nums" style={{ color: "var(--erp-text-strong)" }}>
              x {Number(item.quantity || 0).toLocaleString()}
            </span>
          </div>
        );
      })}
    </div>
  );
}
