"use client";

import { useMemo } from "react";
import { useT } from "@/lib/i18n";

export type StorageMapCell = {
  code: string;
  zone: string;
  count?: number;
  status?: "free" | "partial" | "full";
  matched_count?: number;
};

const ZONE_LAYOUT: Array<{ id: string; cols: number; rows: number; labelKey: string }> = [
  { id: "N", cols: 16, rows: 1, labelKey: "warehouse.zone.unloading" },
  { id: "A", cols: 2, rows: 6, labelKey: "warehouse.zone.women" },
  { id: "B", cols: 2, rows: 6, labelKey: "warehouse.zone.women" },
  { id: "C", cols: 2, rows: 8, labelKey: "warehouse.zone.men" },
  { id: "D", cols: 2, rows: 10, labelKey: "warehouse.zone.new" },
  { id: "E", cols: 2, rows: 10, labelKey: "warehouse.zone.kids" },
  { id: "F", cols: 2, rows: 10, labelKey: "warehouse.zone.new" },
  { id: "G", cols: 2, rows: 8, labelKey: "warehouse.zone.men" },
  { id: "H", cols: 2, rows: 10, labelKey: "warehouse.zone.shipping" },
  { id: "M", cols: 1, rows: 12, labelKey: "warehouse.zone.mezzanine" },
  { id: "K", cols: 2, rows: 1, labelKey: "warehouse.zone.quarantine" },
  { id: "L", cols: 5, rows: 1, labelKey: "warehouse.zone.receiving" },
];

function buildDefaultCells() {
  const rows: StorageMapCell[] = [];
  for (const z of ZONE_LAYOUT) {
    const total = z.cols * z.rows;
    for (let idx = 1; idx <= total; idx++) {
      rows.push({
        code: `${z.id}-${String(idx).padStart(2, "0")}`,
        zone: z.id,
        count: 0,
        status: "free",
        matched_count: 0,
      });
    }
  }
  return rows;
}

const STATUS_CLASS: Record<string, string> = {
  free: "bg-[#e6efe2] border-[#cfe1c7] text-[#2f6b3e]",
  partial: "bg-[#f5ecc8] border-[#e6d6a3] text-[#8a6608]",
  full: "bg-[#f4d4d0] border-[#ebbab5] text-[#a3403e]",
};

export default function WarehouseMap({
  cells,
  selectedCell,
  onSelectCell,
  compact = false,
}: {
  cells?: StorageMapCell[];
  selectedCell?: string | null;
  onSelectCell?: (cellCode: string) => void;
  compact?: boolean;
}) {
  const { t } = useT();
  const normalizedCells = cells?.length ? cells : buildDefaultCells();
  const byCode = useMemo(() => {
    const map = new Map<string, StorageMapCell>();
    for (const c of normalizedCells) map.set(c.code, c);
    return map;
  }, [normalizedCells]);

  const zoneNodes = ZONE_LAYOUT.map((zone) => {
    const total = zone.cols * zone.rows;
    const zoneCells: StorageMapCell[] = [];
    for (let idx = 1; idx <= total; idx++) {
      const code = `${zone.id}-${String(idx).padStart(2, "0")}`;
      zoneCells.push(byCode.get(code) ?? { code, zone: zone.id, status: "free", count: 0, matched_count: 0 });
    }

    return (
      <div key={zone.id} className="rounded-xl border border-[#e3dfd3] bg-[#fdfcf8] p-3">
        <div className="mb-2 flex items-baseline justify-between">
          <div className="text-sm font-semibold text-[#14110b]">{zone.id}</div>
          <div className="text-[10px] uppercase tracking-[0.1em] text-[#8a8472]">{t(zone.labelKey)}</div>
        </div>
        <div
          className="grid gap-1.5"
          style={{ gridTemplateColumns: `repeat(${zone.cols}, minmax(0, 1fr))` }}
        >
          {zoneCells.map((cell) => {
            const cls = STATUS_CLASS[cell.status || "free"] || STATUS_CLASS.free;
            const active = selectedCell && selectedCell === cell.code;
            const hasMatch = !!cell.matched_count && cell.matched_count > 0;
            const isClickable = !!onSelectCell;
            return (
              <button
                key={cell.code}
                type="button"
                onClick={() => onSelectCell?.(cell.code)}
                className={[
                  "relative rounded-md border px-1 py-1 text-[10px] font-semibold transition",
                  cls,
                  isClickable ? "hover:-translate-y-px hover:shadow-sm" : "cursor-default",
                  active ? "ring-2 ring-[#14110b] ring-offset-1" : "",
                  hasMatch ? "shadow-[inset_0_0_0_1px_#c2410c]" : "",
                ].join(" ")}
                title={`${cell.code}${cell.count ? ` - ${cell.count} ${t("field.packageNo")}` : ""}`}
              >
                <div className="leading-tight">{cell.code}</div>
                {!!cell.count && <div className="text-[9px] leading-tight opacity-80">{cell.count}</div>}
                {hasMatch && <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-[#c2410c]" />}
              </button>
            );
          })}
        </div>
      </div>
    );
  });

  if (compact) {
    return <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">{zoneNodes}</div>;
  }
  return <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">{zoneNodes}</div>;
}
