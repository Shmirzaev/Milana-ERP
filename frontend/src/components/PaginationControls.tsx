"use client";
import { useT } from "@/lib/i18n";

type Props = {
  page: number;
  pageSize: number;
  total: number;
  count: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  pageSizeOptions?: number[];
  position?: "top" | "bottom";
};

export default function PaginationControls({
  page,
  pageSize,
  total,
  count,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [12, 24, 25, 50, 100, 200],
  position = "bottom",
}: Props) {
  const { t } = useT();
  const safeTotal = Number(total || 0);
  const start = safeTotal === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = safeTotal === 0 ? 0 : Math.min(safeTotal, start + count - 1);
  const hasPrev = page > 1;
  const hasNext = end < safeTotal;

  return (
    <div className={`flex flex-col gap-3 border-[#ecebe3] px-4 py-3 text-sm text-[#56503f] sm:flex-row sm:flex-wrap sm:items-center sm:justify-between ${position === "top" ? "mb-3 border-b" : "border-t"}`}>
      <div className="min-w-0">
        {t("common.showingRange", { start, end, total: safeTotal })}
      </div>
      <div className="grid w-full grid-cols-[minmax(4.5rem,0.8fr)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-2 sm:flex sm:w-auto">
        <select
          className="input h-9 w-full py-1 text-xs sm:w-24"
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
        >
          {pageSizeOptions.map((size) => <option key={size} value={size}>{size}</option>)}
        </select>
        <button className="btn" disabled={!hasPrev} onClick={() => onPageChange(page - 1)}>{t("common.previous")}</button>
        <button className="btn" disabled={!hasNext} onClick={() => onPageChange(page + 1)}>{t("common.next")}</button>
      </div>
    </div>
  );
}
