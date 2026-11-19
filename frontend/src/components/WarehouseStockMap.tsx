"use client";

import Link from "next/link";
import { useMemo } from "react";
import type { StorageMapCell } from "@/components/WarehouseMap";
import { useT } from "@/lib/i18n";
import { warehouseWorkspaceText } from "@/lib/warehouseWorkspace";

const zones = ["A", "B", "C", "D", "E", "F", "G", "H", "M"];
const colors = { free: "bg-[#e6efe2]", partial: "bg-[#f5ecc8]", full: "bg-[#f4d4d0]" };

export default function WarehouseStockMap({ cells, matches, selectedCell, onSelectCell, filtered, manageUrl }: {
  cells: StorageMapCell[];
  matches: Array<{ storage_cell?: string | null; package_count?: number }>;
  selectedCell: string;
  onSelectCell: (cell: string) => void;
  filtered: boolean;
  manageUrl: string;
}) {
  const { t, lang } = useT();
  const text = warehouseWorkspaceText[lang];
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of matches) if (row.storage_cell) map.set(row.storage_cell, (map.get(row.storage_cell) || 0) + (row.package_count || 1));
    return map;
  }, [matches]);
  function zone(id: string, strip = false) {
    const items = cells.filter(cell => cell.zone === id);
    return <section key={id} className="min-w-0 rounded-md border border-[#e3dfd3] p-2">
      <h3 className="mb-2 text-center text-xs font-semibold">{id}</h3>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${strip ? items.length : id === "M" ? 1 : 2}, minmax(0, 1fr))` }}>
        {items.map(cell => {
          const count = counts.get(cell.code) || 0;
          return <button key={cell.code} type="button" aria-pressed={selectedCell === cell.code}
            aria-label={`${cell.code}: ${count} ${text.matches}`}
            title={`${cell.code}: ${count} / ${cell.count || 0}`}
            onClick={() => onSelectCell(selectedCell === cell.code ? "" : cell.code)}
            className={`min-h-7 rounded border px-0.5 py-1 text-[10px] ${colors[cell.status || "free"]} ${selectedCell === cell.code ? "border-[#14110b] ring-1 ring-[#14110b]" : "border-[#d6d1c4]"} ${filtered && !count ? "opacity-35" : ""}`}>
            {cell.code.split("-")[1]}{count > 0 && <span className="block font-semibold">{count}</span>}
          </button>;
        })}
      </div>
    </section>;
  }
  return <section className="card min-w-0 p-4">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h2 className="app-card-title">{t("page.warehouseMap.mapCardTitle")}</h2>
      <Link className="btn text-xs" href={manageUrl}>{text.location}</Link>
    </div>
    <div className="mb-3 flex flex-wrap gap-3 text-xs text-[#56503f]">
      {(["free", "partial", "full"] as const).map(status => <span key={status} className="inline-flex items-center gap-1"><span className={`h-3 w-3 border border-[#d6d1c4] ${colors[status]}`} />{t(`page.warehouseMap.legend.${status}`)}</span>)}
      {selectedCell && <button type="button" className="underline" onClick={() => onSelectCell("")}>{text.clear}: {selectedCell}</button>}
    </div>
    <div className="overflow-x-auto">
      <div className="min-w-[540px] space-y-3">
        {zone("N", true)}
        <div className="grid grid-cols-9 items-start gap-2">{zones.map(id => zone(id))}</div>
        <div className="grid grid-cols-3 gap-3">{zone("K", true)}<div className="col-span-2">{zone("L", true)}</div></div>
      </div>
    </div>
  </section>;
}
